from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse

from ...auth import get_request_db, require_auth
from ....core.attachments import AttachmentError, LocalAttachmentStore


router = APIRouter()


def _store(request: Request) -> LocalAttachmentStore:
    store = getattr(request.app.state, "attachment_store", None)
    if store is None:
        store = LocalAttachmentStore()
        request.app.state.attachment_store = store
    return store


def _raise_attachment_error(error: AttachmentError) -> None:
    raise HTTPException(
        status_code=error.status_code,
        detail={"code": error.code, "message": error.message},
    ) from error


async def _read_upload(file: UploadFile) -> bytes:
    return await file.read(5 * 1024 * 1024 + 1)


async def _simulator_owner(db, principal: dict[str, str], user_id: str) -> dict[str, Any]:
    if principal.get("role") not in {"manager", "admin"}:
        raise HTTPException(
            status_code=403,
            detail={"code": "SIMULATOR_FORBIDDEN", "message": "Manager access is required."},
        )
    row = await db.fetch_one(
        """
        SELECT employee.id, employee.venue_id
        FROM users AS employee
        WHERE employee.id = ? AND employee.venue_id = ? AND employee.status = 'ACTIVE'
          AND EXISTS (
              SELECT 1 FROM channel_identities AS identity
              WHERE identity.venue_id = employee.venue_id AND identity.user_id = employee.id
                AND identity.channel = 'WECOM_SIMULATOR' AND identity.status = 'ACTIVE'
          )
        """,
        (user_id, principal["venue_id"]),
    )
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "IDENTITY_NOT_AVAILABLE", "message": "Employee identity is unavailable."},
        )
    return row


@router.post("/assistant/attachments", status_code=status.HTTP_201_CREATED)
async def upload_assistant_attachment(
    request: Request,
    file: UploadFile = File(...),
    principal: dict[str, str] = Depends(require_auth),
    db=Depends(get_request_db),
):
    try:
        attachment = await _store(request).create(
            db,
            venue_id=principal["venue_id"],
            owner_user_id=principal["user_id"],
            filename=file.filename or "attachment",
            content_type=file.content_type or "application/octet-stream",
            content=await _read_upload(file),
        )
    except AttachmentError as error:
        _raise_attachment_error(error)
    return {"attachment": attachment}


@router.post("/channels/simulator/attachments", status_code=status.HTTP_201_CREATED)
async def upload_simulator_attachment(
    request: Request,
    user_id: str = Form(..., min_length=1, max_length=64),
    file: UploadFile = File(...),
    principal: dict[str, str] = Depends(require_auth),
    db=Depends(get_request_db),
):
    owner = await _simulator_owner(db, principal, user_id)
    try:
        attachment = await _store(request).create(
            db,
            venue_id=owner["venue_id"],
            owner_user_id=owner["id"],
            filename=file.filename or "attachment",
            content_type=file.content_type or "application/octet-stream",
            content=await _read_upload(file),
        )
    except AttachmentError as error:
        _raise_attachment_error(error)
    return {"attachment": attachment}


@router.get("/assistant/attachments/{attachment_id}/content")
async def get_attachment_content(
    attachment_id: str,
    request: Request,
    principal: dict[str, str] = Depends(require_auth),
    db=Depends(get_request_db),
):
    row = await db.fetch_one(
        """
        SELECT * FROM message_attachments
        WHERE id = ? AND venue_id = ?
        """,
        (attachment_id, principal["venue_id"]),
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    if principal.get("role") not in {"manager", "admin"} and row["owner_user_id"] != principal["user_id"]:
        raise HTTPException(status_code=404, detail="Attachment not found")
    try:
        path = _store(request).resolve(row["storage_key"])
    except AttachmentError as error:
        _raise_attachment_error(error)
    return FileResponse(
        path,
        media_type=row["content_type"],
        filename=row["original_name"],
        content_disposition_type="inline",
    )
