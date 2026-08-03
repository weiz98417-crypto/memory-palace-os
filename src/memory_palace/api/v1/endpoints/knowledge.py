"""Formal knowledge and SOP lifecycle endpoints."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, Query, Request, status
from loguru import logger
from pydantic import BaseModel, Field

from ...audit import request_trace_id, write_audit
from ...auth import get_request_db, require_auth, require_roles
from ...errors import api_error


router = APIRouter(dependencies=[Depends(require_auth)])


class KnowledgeCreateRequest(BaseModel):
    title: str = Field(..., min_length=2, max_length=200)
    content: str = Field(..., min_length=5, max_length=20000)
    category: str = Field("通用", min_length=1, max_length=80)
    source_type: Literal["MANUAL", "EVENT", "SOP", "IMPORT"] = "MANUAL"
    source_id: Optional[str] = Field(None, max_length=128)
    tags: list[str] = Field(default_factory=list, max_length=30)


class KnowledgeUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=2, max_length=200)
    content: Optional[str] = Field(None, min_length=5, max_length=20000)
    category: Optional[str] = Field(None, min_length=1, max_length=80)
    tags: Optional[list[str]] = Field(None, max_length=30)


class KnowledgeImportRequest(BaseModel):
    entries: list[KnowledgeCreateRequest] = Field(..., min_length=1, max_length=100)


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=1000)
    top_k: int = Field(10, ge=1, le=50)
    threshold: float = Field(0.55, ge=0.0, le=1.0)


class SOPCreateRequest(BaseModel):
    title: str = Field(..., min_length=2, max_length=200)
    content: str = Field(..., min_length=10, max_length=30000)
    category: str = Field("通用", min_length=1, max_length=80)
    priority: int = Field(3, ge=0, le=4)
    version: str = Field("1.0", pattern=r"^[1-9]\d{0,2}\.\d{1,2}$")
    source_event_id: Optional[str] = Field(None, max_length=128)


class SOPUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=2, max_length=200)
    content: Optional[str] = Field(None, min_length=10, max_length=30000)
    category: Optional[str] = Field(None, min_length=1, max_length=80)
    priority: Optional[int] = Field(None, ge=0, le=4)
    change_note: Optional[str] = Field(None, max_length=500)


class SOPReviewRequest(BaseModel):
    comment: Optional[str] = Field(None, max_length=1000)


def _vector_store(request: Request):
    container = getattr(request.app.state, "container", None)
    vector_store = getattr(container, "vector_store", None)
    if vector_store is None:
        vector_store = getattr(request.app.state, "vector_store", None)
    if vector_store is None:
        raise api_error(
            request,
            503,
            "VECTOR_STORE_NOT_READY",
            "知识向量服务尚未就绪。",
            "请联系管理员检查 ChromaDB 和 Embedding 配置。",
            retryable=True,
        )
    return vector_store


def _decode_knowledge(row: dict[str, Any]) -> dict[str, Any]:
    try:
        row["tags"] = json.loads(row.pop("tags_json", "[]") or "[]")
    except (TypeError, json.JSONDecodeError):
        row["tags"] = []
    return row


def _knowledge_metadata(
    *,
    knowledge_id: str,
    venue_id: str,
    title: str,
    category: str,
    source_type: str,
    source_id: Optional[str],
    version: int | str,
    status: Optional[str] = None,
    published_at: Optional[float] = None,
    publisher_name: Optional[str] = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "knowledge_id": knowledge_id,
        "venue_id": venue_id,
        "title": title,
        "category": category,
        "source_type": source_type,
        "version": version,
    }
    if source_id:
        metadata["source_id"] = source_id
    if status:
        metadata["status"] = status
    if published_at is not None:
        metadata["published_at"] = published_at
    if publisher_name:
        metadata["publisher_name"] = publisher_name
    return metadata


async def _sop_row(db, sop_id: int, venue_id: str) -> Optional[dict[str, Any]]:
    return await db.fetch_one(
        "SELECT * FROM sop_documents WHERE id = ? AND venue_id = ?",
        (sop_id, venue_id),
    )


async def _snapshot_sop(db, sop: dict[str, Any], user_id: str, note: Optional[str]) -> str:
    snapshot_id = uuid.uuid4().hex
    await db.execute(
        """
        INSERT INTO sop_versions (
            id, sop_id, venue_id, version, title, content, status,
            changed_by, change_note, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot_id,
            sop["id"],
            sop["venue_id"],
            str(sop["version"]),
            sop["title"],
            sop["content"],
            sop["status"],
            user_id,
            note,
            time.time(),
        ),
    )
    return snapshot_id


@router.get("/knowledge")
async def list_knowledge(
    query: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    principal: dict = Depends(require_auth),
    db=Depends(get_request_db),
):
    sql = "SELECT * FROM knowledge_documents WHERE venue_id = ? AND status = 'ACTIVE'"
    params: list[Any] = [principal["venue_id"]]
    if query:
        sql += " AND (title LIKE ? OR content LIKE ?)"
        like = f"%{query}%"
        params.extend([like, like])
    if category:
        sql += " AND category = ?"
        params.append(category)
    sql += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    rows = [_decode_knowledge(row) for row in await db.fetch_all(sql, tuple(params))]
    return {"knowledge": rows, "limit": limit, "offset": offset}


@router.get("/knowledge/{knowledge_id}")
async def get_knowledge(
    knowledge_id: str,
    request: Request,
    principal: dict = Depends(require_auth),
    db=Depends(get_request_db),
):
    row = await db.fetch_one(
        "SELECT * FROM knowledge_documents WHERE id = ? AND venue_id = ? AND status = 'ACTIVE'",
        (knowledge_id, principal["venue_id"]),
    )
    if not row:
        raise api_error(request, 404, "KNOWLEDGE_NOT_FOUND", "知识条目不存在。", "刷新知识列表后重试。")
    return {"knowledge": _decode_knowledge(row)}


@router.post("/knowledge", status_code=status.HTTP_201_CREATED)
async def create_knowledge(
    body: KnowledgeCreateRequest,
    request: Request,
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    vector_store = _vector_store(request)
    knowledge_id = uuid.uuid4().hex
    vector_doc_id = f"knowledge:{principal['venue_id']}:{knowledge_id}"
    now = time.time()
    metadata = _knowledge_metadata(
        knowledge_id=knowledge_id,
        venue_id=principal["venue_id"],
        title=body.title.strip(),
        category=body.category.strip(),
        source_type=body.source_type,
        source_id=body.source_id,
        version=1,
    )
    vector_store.upsert_experience(body.content.strip(), metadata, vector_doc_id, strict=True)
    try:
        await db.execute(
            """
            INSERT INTO knowledge_documents (
                id, venue_id, title, content, category, source_type, source_id,
                version, status, tags_json, vector_doc_id, created_by,
                updated_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, 'ACTIVE', ?, ?, ?, ?, ?, ?)
            """,
            (
                knowledge_id,
                principal["venue_id"],
                body.title.strip(),
                body.content.strip(),
                body.category.strip(),
                body.source_type,
                body.source_id,
                json.dumps(body.tags, ensure_ascii=False),
                vector_doc_id,
                principal["user_id"],
                principal["user_id"],
                now,
                now,
            ),
        )
    except Exception:
        vector_store.delete_experience(vector_doc_id)
        raise
    trace_id = request_trace_id(request)
    await write_audit(
        db,
        principal=principal,
        action="KNOWLEDGE_CREATED",
        resource_type="knowledge",
        resource_id=knowledge_id,
        outcome="SUCCEEDED",
        trace_id=trace_id,
        metadata={"source_type": body.source_type, "source_id": body.source_id},
    )
    row = await db.fetch_one("SELECT * FROM knowledge_documents WHERE id = ?", (knowledge_id,))
    return {"knowledge": _decode_knowledge(row), "trace_id": trace_id}


@router.put("/knowledge/{knowledge_id}")
async def update_knowledge(
    knowledge_id: str,
    body: KnowledgeUpdateRequest,
    request: Request,
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    current = await db.fetch_one(
        "SELECT * FROM knowledge_documents WHERE id = ? AND venue_id = ? AND status = 'ACTIVE'",
        (knowledge_id, principal["venue_id"]),
    )
    if not current:
        raise api_error(request, 404, "KNOWLEDGE_NOT_FOUND", "知识条目不存在。", "刷新知识列表后重试。")
    updates = body.model_dump(exclude_none=True)
    if not updates:
        return {"knowledge": _decode_knowledge(current), "trace_id": request_trace_id(request)}
    tags = updates.pop("tags", None)
    new_title = updates.get("title", current["title"]).strip()
    new_content = updates.get("content", current["content"]).strip()
    new_category = updates.get("category", current["category"]).strip()
    new_version = int(current["version"]) + 1
    vector_store = _vector_store(request)
    metadata = _knowledge_metadata(
        knowledge_id=knowledge_id,
        venue_id=principal["venue_id"],
        title=new_title,
        category=new_category,
        source_type=current["source_type"],
        source_id=current.get("source_id"),
        version=new_version,
    )
    vector_store.upsert_experience(new_content, metadata, current["vector_doc_id"], strict=True)
    try:
        await db.execute(
            """
            UPDATE knowledge_documents
            SET title = ?, content = ?, category = ?, tags_json = ?,
                version = ?, updated_by = ?, updated_at = ?
            WHERE id = ? AND venue_id = ?
            """,
            (
                new_title,
                new_content,
                new_category,
                json.dumps(tags, ensure_ascii=False) if tags is not None else current["tags_json"],
                new_version,
                principal["user_id"],
                time.time(),
                knowledge_id,
                principal["venue_id"],
            ),
        )
    except Exception:
        old_metadata = _knowledge_metadata(
            knowledge_id=knowledge_id,
            venue_id=principal["venue_id"],
            title=current["title"],
            category=current["category"],
            source_type=current["source_type"],
            source_id=current.get("source_id"),
            version=int(current["version"]),
        )
        vector_store.upsert_experience(current["content"], old_metadata, current["vector_doc_id"])
        raise
    trace_id = request_trace_id(request)
    await write_audit(
        db,
        principal=principal,
        action="KNOWLEDGE_UPDATED",
        resource_type="knowledge",
        resource_id=knowledge_id,
        outcome="SUCCEEDED",
        trace_id=trace_id,
        metadata={"version": new_version, "changed_fields": sorted(body.model_dump(exclude_none=True))},
    )
    row = await db.fetch_one("SELECT * FROM knowledge_documents WHERE id = ?", (knowledge_id,))
    return {"knowledge": _decode_knowledge(row), "trace_id": trace_id}


@router.delete("/knowledge/{knowledge_id}")
async def delete_knowledge(
    knowledge_id: str,
    request: Request,
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    current = await db.fetch_one(
        "SELECT * FROM knowledge_documents WHERE id = ? AND venue_id = ? AND status = 'ACTIVE'",
        (knowledge_id, principal["venue_id"]),
    )
    if not current:
        raise api_error(request, 404, "KNOWLEDGE_NOT_FOUND", "知识条目不存在。", "刷新知识列表后重试。")
    vector_store = _vector_store(request)
    vector_store.delete_experience(current["vector_doc_id"], strict=True)
    try:
        await db.execute(
            "UPDATE knowledge_documents SET status = 'DELETED', updated_by = ?, updated_at = ? WHERE id = ? AND venue_id = ?",
            (principal["user_id"], time.time(), knowledge_id, principal["venue_id"]),
        )
    except Exception:
        metadata = _knowledge_metadata(
            knowledge_id=knowledge_id,
            venue_id=principal["venue_id"],
            title=current["title"],
            category=current["category"],
            source_type=current["source_type"],
            source_id=current.get("source_id"),
            version=int(current["version"]),
        )
        vector_store.upsert_experience(
            current["content"],
            metadata,
            current["vector_doc_id"],
            strict=True,
        )
        raise
    trace_id = request_trace_id(request)
    await write_audit(
        db,
        principal=principal,
        action="KNOWLEDGE_DELETED",
        resource_type="knowledge",
        resource_id=knowledge_id,
        outcome="SUCCEEDED",
        trace_id=trace_id,
    )
    return {"deleted": True, "knowledge_id": knowledge_id, "trace_id": trace_id}


@router.post("/knowledge/search")
async def search_knowledge(
    body: KnowledgeSearchRequest,
    request: Request,
    principal: dict = Depends(require_auth),
):
    results = _vector_store(request).query_experience(
        body.query.strip(),
        top_k=body.top_k,
        threshold=body.threshold,
        venue_id=principal["venue_id"],
        strict=True,
    )
    return {"results": results, "query": body.query.strip()}


@router.post("/knowledge/import")
async def import_knowledge(
    body: KnowledgeImportRequest,
    request: Request,
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    vector_store = _vector_store(request)
    batch_id = uuid.uuid4().hex
    created: list[tuple[str, str]] = []
    now = time.time()
    try:
        for entry in body.entries:
            knowledge_id = uuid.uuid4().hex
            vector_doc_id = f"knowledge:{principal['venue_id']}:{knowledge_id}"
            metadata = _knowledge_metadata(
                knowledge_id=knowledge_id,
                venue_id=principal["venue_id"],
                title=entry.title.strip(),
                category=entry.category.strip(),
                source_type="IMPORT",
                source_id=entry.source_id,
                version=1,
            )
            vector_store.upsert_experience(entry.content.strip(), metadata, vector_doc_id, strict=True)
            created.append((knowledge_id, vector_doc_id))
            await db.execute(
                """
                INSERT INTO knowledge_documents (
                    id, venue_id, title, content, category, source_type, source_id,
                    version, status, tags_json, vector_doc_id, import_batch_id,
                    created_by, updated_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'IMPORT', ?, 1, 'ACTIVE', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    knowledge_id,
                    principal["venue_id"],
                    entry.title.strip(),
                    entry.content.strip(),
                    entry.category.strip(),
                    entry.source_id,
                    json.dumps(entry.tags, ensure_ascii=False),
                    vector_doc_id,
                    batch_id,
                    principal["user_id"],
                    principal["user_id"],
                    now,
                    now,
                ),
            )
    except Exception:
        for knowledge_id, vector_doc_id in created:
            vector_store.delete_experience(vector_doc_id)
            await db.execute("DELETE FROM knowledge_documents WHERE id = ?", (knowledge_id,))
        raise
    trace_id = request_trace_id(request)
    await write_audit(
        db,
        principal=principal,
        action="KNOWLEDGE_IMPORTED",
        resource_type="knowledge_batch",
        resource_id=batch_id,
        outcome="SUCCEEDED",
        trace_id=trace_id,
        metadata={"count": len(created)},
    )
    return {"batch_id": batch_id, "imported": len(created), "trace_id": trace_id}


@router.post("/knowledge/rebuild-index")
async def rebuild_knowledge_index(
    request: Request,
    principal: dict = Depends(require_roles("admin")),
    db=Depends(get_request_db),
):
    vector_store = _vector_store(request)
    rows = await db.fetch_all(
        "SELECT * FROM knowledge_documents WHERE venue_id = ? AND status = 'ACTIVE' ORDER BY created_at",
        (principal["venue_id"],),
    )
    rebuilt = 0
    for row in rows:
        metadata = _knowledge_metadata(
            knowledge_id=row["id"],
            venue_id=row["venue_id"],
            title=row["title"],
            category=row["category"],
            source_type=row["source_type"],
            source_id=row.get("source_id"),
            version=int(row["version"]),
        )
        vector_store.upsert_experience(row["content"], metadata, row["vector_doc_id"], strict=True)
        rebuilt += 1
    trace_id = request_trace_id(request)
    await write_audit(
        db,
        principal=principal,
        action="KNOWLEDGE_INDEX_REBUILT",
        resource_type="knowledge_index",
        resource_id=principal["venue_id"],
        outcome="SUCCEEDED",
        trace_id=trace_id,
        metadata={"count": rebuilt},
    )
    return {"rebuilt": rebuilt, "trace_id": trace_id}


@router.get("/sops")
async def list_sops(
    sop_status: Optional[str] = Query(None, alias="status"),
    category: Optional[str] = None,
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    sql = "SELECT * FROM sop_documents WHERE venue_id = ?"
    params: list[Any] = [principal["venue_id"]]
    if sop_status:
        sql += " AND status = ?"
        params.append(sop_status.upper())
    if category:
        sql += " AND category = ?"
        params.append(category)
    sql += " ORDER BY updated_at DESC"
    return {"sops": await db.fetch_all(sql, tuple(params))}


@router.get("/sops/{sop_id}")
async def get_sop(
    sop_id: int,
    request: Request,
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    sop = await _sop_row(db, sop_id, principal["venue_id"])
    if not sop:
        raise api_error(request, 404, "SOP_NOT_FOUND", "SOP 不存在。", "刷新 SOP 列表后重试。")
    versions = await db.fetch_all(
        "SELECT * FROM sop_versions WHERE sop_id = ? AND venue_id = ? ORDER BY created_at DESC",
        (sop_id, principal["venue_id"]),
    )
    return {"sop": sop, "versions": versions}


@router.post("/sops", status_code=status.HTTP_201_CREATED)
async def create_sop(
    body: SOPCreateRequest,
    request: Request,
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    if body.source_event_id and not await db.fetch_one(
        "SELECT event_id FROM confirmed_events WHERE event_id = ? AND venue_id = ?",
        (body.source_event_id, principal["venue_id"]),
    ):
        raise api_error(request, 400, "SOP_SOURCE_EVENT_INVALID", "来源事件不存在或不属于当前场地。", "重新选择来源事件。")
    await db.execute(
        """
        INSERT INTO sop_documents (
            venue_id, category, title, content, priority, version, status,
            source_event_id, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'DRAFT', ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        (
            principal["venue_id"],
            body.category.strip(),
            body.title.strip(),
            body.content.strip(),
            body.priority,
            body.version,
            body.source_event_id,
            principal["user_id"],
        ),
    )
    sop = await db.fetch_one(
        "SELECT * FROM sop_documents WHERE venue_id = ? AND created_by = ? ORDER BY id DESC LIMIT 1",
        (principal["venue_id"], principal["user_id"]),
    )
    await _snapshot_sop(db, sop, principal["user_id"], "创建草稿")
    trace_id = request_trace_id(request)
    await write_audit(
        db,
        principal=principal,
        action="SOP_CREATED",
        resource_type="sop",
        resource_id=str(sop["id"]),
        outcome="SUCCEEDED",
        trace_id=trace_id,
        metadata={"source_event_id": body.source_event_id, "version": body.version},
    )
    return {"sop": sop, "trace_id": trace_id}


@router.put("/sops/{sop_id}")
async def update_sop(
    sop_id: int,
    body: SOPUpdateRequest,
    request: Request,
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    current = await _sop_row(db, sop_id, principal["venue_id"])
    if not current:
        raise api_error(request, 404, "SOP_NOT_FOUND", "SOP 不存在。", "刷新 SOP 列表后重试。")
    if current["status"] not in {"DRAFT", "REJECTED"}:
        raise api_error(request, 409, "SOP_NOT_EDITABLE", "当前状态的 SOP 不允许编辑。", "等待审核结果或创建新版本。")
    updates = body.model_dump(exclude_none=True)
    change_note = updates.pop("change_note", None)
    if not updates:
        return {"sop": current, "trace_id": request_trace_id(request)}
    major, _, minor = str(current["version"]).partition(".")
    version = f"{int(major or 1)}.{int(minor or 0) + 1}"
    set_sql = ", ".join(f"{column} = ?" for column in updates)
    await db.execute(
        f"UPDATE sop_documents SET {set_sql}, version = ?, status = 'DRAFT', updated_at = CURRENT_TIMESTAMP WHERE id = ? AND venue_id = ?",
        (*updates.values(), version, sop_id, principal["venue_id"]),
    )
    sop = await _sop_row(db, sop_id, principal["venue_id"])
    await _snapshot_sop(db, sop, principal["user_id"], change_note or "更新草稿")
    trace_id = request_trace_id(request)
    await write_audit(
        db,
        principal=principal,
        action="SOP_UPDATED",
        resource_type="sop",
        resource_id=str(sop_id),
        outcome="SUCCEEDED",
        trace_id=trace_id,
        metadata={"version": version, "changed_fields": sorted(updates)},
    )
    return {"sop": sop, "trace_id": trace_id}


@router.post("/sops/{sop_id}/submit")
async def submit_sop(
    sop_id: int,
    request: Request,
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    sop = await _sop_row(db, sop_id, principal["venue_id"])
    if not sop:
        raise api_error(request, 404, "SOP_NOT_FOUND", "SOP 不存在。", "刷新 SOP 列表后重试。")
    if sop["status"] not in {"DRAFT", "REJECTED"}:
        raise api_error(request, 409, "SOP_NOT_SUBMITTABLE", "当前 SOP 不能重复提交审核。", "查看当前审核状态。")
    await db.execute(
        "UPDATE sop_documents SET status = 'IN_REVIEW', updated_at = CURRENT_TIMESTAMP WHERE id = ? AND venue_id = ?",
        (sop_id, principal["venue_id"]),
    )
    submitted = await _sop_row(db, sop_id, principal["venue_id"])
    await _snapshot_sop(db, submitted, principal["user_id"], "提交审核")
    trace_id = request_trace_id(request)
    await write_audit(
        db,
        principal=principal,
        action="SOP_SUBMITTED",
        resource_type="sop",
        resource_id=str(sop_id),
        outcome="SUCCEEDED",
        trace_id=trace_id,
    )
    return {"sop": submitted, "trace_id": trace_id}


@router.post("/sops/{sop_id}/publish")
async def publish_sop(
    sop_id: int,
    body: SOPReviewRequest,
    request: Request,
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    sop = await _sop_row(db, sop_id, principal["venue_id"])
    if not sop:
        raise api_error(request, 404, "SOP_NOT_FOUND", "SOP 不存在。", "刷新 SOP 列表后重试。")
    if sop["status"] != "IN_REVIEW":
        raise api_error(request, 409, "SOP_NOT_IN_REVIEW", "只有审核中的 SOP 可以发布。", "先提交审核。")
    vector_store = _vector_store(request)
    knowledge_id = f"sop-{sop_id}"
    vector_doc_id = f"sop:{principal['venue_id']}:{sop_id}"
    previous_knowledge = await db.fetch_one(
        "SELECT * FROM knowledge_documents WHERE id = ? AND venue_id = ?",
        (knowledge_id, principal["venue_id"]),
    )
    publisher = await db.fetch_one(
        "SELECT display_name, username FROM users WHERE id = ? AND venue_id = ?",
        (principal["user_id"], principal["venue_id"]),
    )
    publisher_name = (
        (publisher or {}).get("display_name")
        or (publisher or {}).get("username")
        or principal.get("username")
        or "知识负责人"
    )
    now = time.time()
    metadata = _knowledge_metadata(
        knowledge_id=knowledge_id,
        venue_id=principal["venue_id"],
        title=sop["title"],
        category=sop["category"],
        source_type="SOP",
        source_id=str(sop_id),
        version=sop["version"],
        status="PUBLISHED",
        published_at=now,
        publisher_name=publisher_name,
    )
    trace_id = request_trace_id(request)
    vector_written = False
    snapshot_id: Optional[str] = None
    try:
        vector_store.upsert_experience(sop["content"], metadata, vector_doc_id, strict=True)
        vector_written = True
        await db.execute(
            """
            UPDATE sop_documents
            SET status = 'PUBLISHED', reviewed_by = ?, published_at = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND venue_id = ?
            """,
            (principal["user_id"], now, sop_id, principal["venue_id"]),
        )
        await db.execute(
            """
            INSERT INTO knowledge_documents (
                id, venue_id, title, content, category, source_type, source_id,
                version, status, tags_json, vector_doc_id, created_by, updated_by,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'SOP', ?, 1, 'ACTIVE', '[]', ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                content = excluded.content,
                category = excluded.category,
                status = 'ACTIVE',
                vector_doc_id = excluded.vector_doc_id,
                updated_by = excluded.updated_by,
                updated_at = excluded.updated_at,
                version = knowledge_documents.version + 1
            """,
            (
                knowledge_id,
                principal["venue_id"],
                sop["title"],
                sop["content"],
                sop["category"],
                str(sop_id),
                vector_doc_id,
                principal["user_id"],
                principal["user_id"],
                now,
                now,
            ),
        )
        published = await _sop_row(db, sop_id, principal["venue_id"])
        snapshot_id = await _snapshot_sop(
            db,
            published,
            principal["user_id"],
            body.comment or "审核通过并发布",
        )
        await write_audit(
            db,
            principal=principal,
            action="SOP_PUBLISHED",
            resource_type="sop",
            resource_id=str(sop_id),
            outcome="SUCCEEDED",
            trace_id=trace_id,
            metadata={"version": published["version"]},
        )
        return {"sop": published, "trace_id": trace_id}
    except Exception as exc:
        rollback_errors: list[str] = []

        if snapshot_id:
            try:
                await db.execute("DELETE FROM sop_versions WHERE id = ?", (snapshot_id,))
            except Exception as rollback_exc:
                rollback_errors.append(f"sop_version:{type(rollback_exc).__name__}")

        try:
            if previous_knowledge is None:
                await db.execute("DELETE FROM knowledge_documents WHERE id = ?", (knowledge_id,))
            else:
                await db.execute(
                    """
                    UPDATE knowledge_documents
                    SET venue_id = ?, title = ?, content = ?, category = ?, source_type = ?,
                        source_id = ?, version = ?, status = ?, tags_json = ?, vector_doc_id = ?,
                        import_batch_id = ?, created_by = ?, updated_by = ?, created_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        previous_knowledge["venue_id"],
                        previous_knowledge["title"],
                        previous_knowledge["content"],
                        previous_knowledge["category"],
                        previous_knowledge["source_type"],
                        previous_knowledge.get("source_id"),
                        previous_knowledge["version"],
                        previous_knowledge["status"],
                        previous_knowledge["tags_json"],
                        previous_knowledge.get("vector_doc_id"),
                        previous_knowledge.get("import_batch_id"),
                        previous_knowledge["created_by"],
                        previous_knowledge["updated_by"],
                        previous_knowledge["created_at"],
                        previous_knowledge["updated_at"],
                        knowledge_id,
                    ),
                )
        except Exception as rollback_exc:
            rollback_errors.append(f"knowledge:{type(rollback_exc).__name__}")

        try:
            await db.execute(
                """
                UPDATE sop_documents
                SET status = ?, reviewed_by = ?, published_at = ?, updated_at = ?
                WHERE id = ? AND venue_id = ?
                """,
                (
                    sop["status"],
                    sop.get("reviewed_by"),
                    sop.get("published_at"),
                    sop["updated_at"],
                    sop_id,
                    principal["venue_id"],
                ),
            )
        except Exception as rollback_exc:
            rollback_errors.append(f"sop:{type(rollback_exc).__name__}")

        if vector_written:
            try:
                if previous_knowledge is None:
                    vector_store.delete_experience(vector_doc_id, strict=True)
                else:
                    previous_vector_doc_id = previous_knowledge.get("vector_doc_id") or vector_doc_id
                    if previous_vector_doc_id != vector_doc_id:
                        vector_store.delete_experience(vector_doc_id, strict=True)
                    previous_metadata = _knowledge_metadata(
                        knowledge_id=previous_knowledge["id"],
                        venue_id=previous_knowledge["venue_id"],
                        title=previous_knowledge["title"],
                        category=previous_knowledge["category"],
                        source_type=previous_knowledge["source_type"],
                        source_id=previous_knowledge.get("source_id"),
                        version=int(previous_knowledge["version"]),
                    )
                    vector_store.upsert_experience(
                        previous_knowledge["content"],
                        previous_metadata,
                        previous_vector_doc_id,
                        strict=True,
                    )
            except Exception as rollback_exc:
                rollback_errors.append(f"vector:{type(rollback_exc).__name__}")

        try:
            await write_audit(
                db,
                principal=principal,
                action="SOP_PUBLISH_FAILED",
                resource_type="sop",
                resource_id=str(sop_id),
                outcome="FAILED",
                trace_id=trace_id,
                metadata={
                    "error_type": type(exc).__name__,
                    "rollback_errors": rollback_errors,
                },
            )
        except Exception as audit_exc:
            rollback_errors.append(f"audit:{type(audit_exc).__name__}")

        if rollback_errors:
            logger.error(
                "SOP publish compensation incomplete: sop_id={}, rollback_errors={}",
                sop_id,
                rollback_errors,
            )
            raise RuntimeError("SOP publish compensation failed") from exc
        raise


@router.post("/sops/{sop_id}/reject")
async def reject_sop(
    sop_id: int,
    body: SOPReviewRequest,
    request: Request,
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    sop = await _sop_row(db, sop_id, principal["venue_id"])
    if not sop:
        raise api_error(request, 404, "SOP_NOT_FOUND", "SOP 不存在。", "刷新 SOP 列表后重试。")
    if sop["status"] != "IN_REVIEW":
        raise api_error(request, 409, "SOP_NOT_IN_REVIEW", "只有审核中的 SOP 可以驳回。", "查看当前状态。")
    if not body.comment:
        raise api_error(request, 422, "SOP_REJECTION_COMMENT_REQUIRED", "驳回时必须填写原因。", "补充修改意见后重试。")
    await db.execute(
        "UPDATE sop_documents SET status = 'REJECTED', reviewed_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND venue_id = ?",
        (principal["user_id"], sop_id, principal["venue_id"]),
    )
    rejected = await _sop_row(db, sop_id, principal["venue_id"])
    await _snapshot_sop(db, rejected, principal["user_id"], body.comment)
    trace_id = request_trace_id(request)
    await write_audit(
        db,
        principal=principal,
        action="SOP_REJECTED",
        resource_type="sop",
        resource_id=str(sop_id),
        outcome="SUCCEEDED",
        trace_id=trace_id,
        metadata={"comment": body.comment},
    )
    return {"sop": rejected, "trace_id": trace_id}
