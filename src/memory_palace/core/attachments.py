from __future__ import annotations

import hashlib
import os
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

from .business_ids import build_business_id


MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {
    "image/jpeg": (".jpg", lambda data: data.startswith(b"\xff\xd8\xff")),
    "image/png": (".png", lambda data: data.startswith(b"\x89PNG\r\n\x1a\n")),
    "image/webp": (
        ".webp",
        lambda data: len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP",
    ),
}
EICAR_MARKER = b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE"


class AttachmentError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def attachment_storage_root() -> Path:
    configured = os.getenv("ATTACHMENT_STORAGE_DIR", "").strip()
    if configured:
        return Path(configured).resolve()
    return (Path(__file__).resolve().parents[3] / "data" / "attachments").resolve()


def _safe_original_name(value: str) -> str:
    name = Path(value or "attachment").name.strip()
    return (name or "attachment")[:180]


def _attachment_payload(row: dict[str, Any], *, description: str = "") -> dict[str, Any]:
    return {
        "attachment_id": row["id"],
        "business_id": row["business_id"],
        "name": row["original_name"],
        "content_type": row["content_type"],
        "size_bytes": int(row["size_bytes"]),
        "sha256": row["sha256"],
        "scan_status": row["scan_status"],
        "scan_engine": row["scan_engine"],
        "external_ref": row["external_ref"],
        "thumbnail_url": row["external_ref"],
        "description": description or row.get("description") or "",
        "uploaded_by": row["owner_user_id"],
        "uploaded_by_name": row.get("uploaded_by_name") or "企业员工",
        "created_at": float(row["created_at"]),
    }


class LocalAttachmentStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or attachment_storage_root()).resolve()

    async def create(
        self,
        database,
        *,
        venue_id: str,
        owner_user_id: str,
        filename: str,
        content_type: str,
        content: bytes,
    ) -> dict[str, Any]:
        normalized_type = str(content_type or "").split(";", 1)[0].strip().lower()
        type_rule = ALLOWED_IMAGE_TYPES.get(normalized_type)
        if type_rule is None:
            raise AttachmentError(
                "ATTACHMENT_TYPE_NOT_ALLOWED",
                "仅支持 JPG、PNG 或 WebP 现场图片。",
                status_code=422,
            )
        if not content:
            raise AttachmentError(
                "ATTACHMENT_EMPTY",
                "附件内容为空，请重新选择图片。",
                status_code=422,
            )
        if len(content) > MAX_ATTACHMENT_BYTES:
            raise AttachmentError(
                "ATTACHMENT_TOO_LARGE",
                "单个现场图片不能超过 5 MB。",
                status_code=413,
            )
        if EICAR_MARKER in content.upper():
            raise AttachmentError(
                "ATTACHMENT_SECURITY_REJECTED",
                "附件未通过安全检查，已拒绝上传。",
                status_code=422,
            )
        extension, signature_matches = type_rule
        if not signature_matches(content):
            raise AttachmentError(
                "ATTACHMENT_SIGNATURE_INVALID",
                "图片内容与文件类型不一致，请重新导出后上传。",
                status_code=422,
            )

        attachment_id = uuid.uuid4().hex
        created_at = time.time()
        business_id = build_business_id("FJ", attachment_id, created_at)
        venue_folder = self.root / hashlib.sha256(venue_id.encode("utf-8")).hexdigest()[:16]
        venue_folder.mkdir(parents=True, exist_ok=True)
        object_path = (venue_folder / f"{attachment_id}{extension}").resolve()
        if self.root not in object_path.parents:
            raise AttachmentError(
                "ATTACHMENT_STORAGE_INVALID",
                "附件存储路径无效。",
                status_code=500,
            )
        object_path.write_bytes(content)
        storage_key = object_path.relative_to(self.root).as_posix()
        external_ref = f"/api/v1/assistant/attachments/{attachment_id}/content"
        try:
            await database.execute(
                """
                INSERT INTO message_attachments (
                    id, business_id, venue_id, owner_user_id, original_name,
                    content_type, size_bytes, sha256, scan_status, scan_engine,
                    storage_key, external_ref, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PASSED',
                          'MVP_SIGNATURE_SCAN_V1', ?, ?, ?)
                """,
                (
                    attachment_id,
                    business_id,
                    venue_id,
                    owner_user_id,
                    _safe_original_name(filename),
                    normalized_type,
                    len(content),
                    hashlib.sha256(content).hexdigest(),
                    storage_key,
                    external_ref,
                    created_at,
                ),
            )
        except Exception:
            object_path.unlink(missing_ok=True)
            raise
        row = await database.fetch_one(
            "SELECT * FROM message_attachments WHERE id = ? AND venue_id = ?",
            (attachment_id, venue_id),
        )
        return _attachment_payload(row)

    def resolve(self, storage_key: str) -> Path:
        object_path = (self.root / storage_key).resolve()
        if self.root not in object_path.parents or not object_path.is_file():
            raise AttachmentError(
                "ATTACHMENT_OBJECT_MISSING",
                "附件对象不存在或已被移除。",
                status_code=404,
            )
        return object_path


async def prepare_message_attachments(
    database,
    *,
    venue_id: str,
    owner_user_id: str,
    attachments: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    prepared = []
    seen = set()
    for item in attachments:
        if not isinstance(item, dict):
            raise AttachmentError(
                "ATTACHMENT_REFERENCE_INVALID",
                "附件引用格式无效。",
                status_code=422,
            )
        attachment_id = str(item.get("attachment_id") or "").strip()
        if not attachment_id or attachment_id in seen:
            raise AttachmentError(
                "ATTACHMENT_REFERENCE_INVALID",
                "附件引用缺少有效编号或重复提交。",
                status_code=422,
            )
        seen.add(attachment_id)
        row = await database.fetch_one(
            """
            SELECT attachment.*, uploader.display_name AS uploaded_by_name
            FROM message_attachments AS attachment
            LEFT JOIN users AS uploader
              ON uploader.id = attachment.owner_user_id AND uploader.venue_id = attachment.venue_id
            WHERE attachment.id = ? AND attachment.venue_id = ?
            """,
            (attachment_id, venue_id),
        )
        if row is None:
            raise AttachmentError(
                "ATTACHMENT_NOT_FOUND",
                "附件不存在或不属于当前场地。",
                status_code=404,
            )
        if row["owner_user_id"] != owner_user_id:
            raise AttachmentError(
                "ATTACHMENT_NOT_OWNED",
                "只能发送当前员工本人上传的附件。",
                status_code=403,
            )
        if row["scan_status"] != "PASSED":
            raise AttachmentError(
                "ATTACHMENT_SECURITY_REJECTED",
                "附件未通过安全检查，不能发送。",
                status_code=422,
            )
        existing_link = await database.fetch_one(
            """
            SELECT message_id FROM message_attachment_links
            WHERE venue_id = ? AND attachment_id = ?
            """,
            (venue_id, attachment_id),
        )
        if existing_link:
            raise AttachmentError(
                "ATTACHMENT_ALREADY_USED",
                "该附件已发送，不能绑定到另一条消息。",
                status_code=409,
            )
        description = str(item.get("description") or "").strip()[:500]
        prepared.append({"row": row, "description": description})
    return prepared


async def link_message_attachments(
    database,
    *,
    venue_id: str,
    message_id: str,
    prepared: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    inserted_ids = []
    try:
        for item in prepared:
            attachment_id = item["row"]["id"]
            link_id = str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"memory-palace-attachment-link:{venue_id}:{message_id}:{attachment_id}",
                )
            )
            await database.execute(
                """
                INSERT INTO message_attachment_links (
                    id, venue_id, message_id, attachment_id, description, linked_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    link_id,
                    venue_id,
                    message_id,
                    attachment_id,
                    item["description"],
                    time.time(),
                ),
            )
            inserted_ids.append(link_id)
    except Exception:
        for link_id in inserted_ids:
            try:
                await database.execute(
                    "DELETE FROM message_attachment_links WHERE id = ? AND venue_id = ?",
                    (link_id, venue_id),
                )
            except Exception:
                pass
        raise
    return [
        _attachment_payload(item["row"], description=item["description"])
        for item in prepared
    ]


async def message_attachments(
    database,
    *,
    venue_id: str,
    message_ids: Iterable[str],
) -> dict[str, list[dict[str, Any]]]:
    normalized_ids = [str(message_id) for message_id in dict.fromkeys(message_ids) if message_id]
    result = {message_id: [] for message_id in normalized_ids}
    if not normalized_ids:
        return result
    placeholders = ",".join("?" for _ in normalized_ids)
    rows = await database.fetch_all(
        f"""
        SELECT link.message_id, link.description,
               attachment.*, uploader.display_name AS uploaded_by_name
        FROM message_attachment_links AS link
        JOIN message_attachments AS attachment
          ON attachment.id = link.attachment_id AND attachment.venue_id = link.venue_id
        LEFT JOIN users AS uploader
          ON uploader.id = attachment.owner_user_id AND uploader.venue_id = attachment.venue_id
        WHERE link.venue_id = ? AND link.message_id IN ({placeholders})
        ORDER BY link.linked_at, attachment.id
        """,
        (venue_id, *normalized_ids),
    )
    for row in rows:
        result.setdefault(str(row["message_id"]), []).append(_attachment_payload(row))
    return result


async def attachment_records(
    database,
    *,
    venue_id: str,
    attachment_ids: Iterable[str],
) -> dict[str, dict[str, Any]]:
    normalized_ids = [
        str(attachment_id)
        for attachment_id in dict.fromkeys(attachment_ids)
        if attachment_id
    ]
    if not normalized_ids:
        return {}
    placeholders = ",".join("?" for _ in normalized_ids)
    rows = await database.fetch_all(
        f"""
        SELECT attachment.*, uploader.display_name AS uploaded_by_name
        FROM message_attachments AS attachment
        LEFT JOIN users AS uploader
          ON uploader.id = attachment.owner_user_id
         AND uploader.venue_id = attachment.venue_id
        WHERE attachment.venue_id = ?
          AND attachment.id IN ({placeholders})
        """,
        (venue_id, *normalized_ids),
    )
    return {
        str(row["id"]): _attachment_payload(row)
        for row in rows
    }
