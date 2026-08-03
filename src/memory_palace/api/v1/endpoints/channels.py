"""Channel identity and canonical message adapter endpoints."""

import json
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ...auth import get_request_db, require_auth
from ....config.integration_readiness import wechat_integration_readiness
from ....core.canonical_ingress import (
    CanonicalIngressError,
    CanonicalMessageIngress,
    IngressMessage,
)
from ....core.queue_worker import get_message_queue
from ....core.simulator_outbox import load_simulator_outbox
from ..schemas import (
    CanonicalMessageAcceptedResponse,
    ChannelIdentityCreateRequest,
    ChannelIdentityResponse,
    SimulatorIdentitiesResponse,
    SimulatorMessageCreateRequest,
    SimulatorOutboxResponse,
    WeComMessageCreateRequest,
)


router = APIRouter()


def _require_simulator_operator(principal: dict[str, str]) -> None:
    if principal.get("role") not in {"manager", "admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "SIMULATOR_FORBIDDEN", "message": "Manager access is required."},
        )


def _require_admin(principal: dict[str, str]) -> None:
    if principal.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "CHANNEL_ADMIN_FORBIDDEN", "message": "Admin access is required."},
        )


def _raise_ingress_error(exc: CanonicalIngressError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    ) from exc


@router.get("/simulator-identities", response_model=SimulatorIdentitiesResponse)
async def list_simulator_identities(
    principal: dict[str, str] = Depends(require_auth),
    db=Depends(get_request_db),
):
    _require_simulator_operator(principal)
    rows = await db.fetch_all(
        """
        SELECT u.id AS user_id, u.username, u.display_name, u.role,
               u.venue_id, u.department, u.job_title, u.status,
               v.name AS venue_name,
               COALESCE(org.setting_value, v.name) AS organization_name,
               (
                   SELECT ci.external_tenant_id
                   FROM channel_identities ci
                   WHERE ci.venue_id = u.venue_id AND ci.user_id = u.id
                     AND ci.channel = 'WECOM' AND ci.status = 'ACTIVE'
                   ORDER BY ci.updated_at DESC
                   LIMIT 1
               ) AS external_tenant_id,
               (
                   SELECT ci.external_user_id
                   FROM channel_identities ci
                   WHERE ci.venue_id = u.venue_id AND ci.user_id = u.id
                     AND ci.channel = 'WECOM' AND ci.status = 'ACTIVE'
                   ORDER BY ci.updated_at DESC
                   LIMIT 1
               ) AS external_user_id,
               CASE WHEN EXISTS (
                   SELECT 1
                   FROM channel_identities ci
                   WHERE ci.venue_id = u.venue_id AND ci.user_id = u.id
                     AND ci.channel = 'WECOM' AND ci.status = 'ACTIVE'
               ) THEN 'ACTIVE' ELSE 'UNBOUND' END AS wecom_binding_status
        FROM users u
        JOIN venues v ON v.id = u.venue_id AND v.status = 'ACTIVE'
        LEFT JOIN system_settings org
          ON org.venue_id = u.venue_id AND org.setting_key = 'organization_name'
        WHERE u.venue_id = ? AND u.status = 'ACTIVE'
          AND u.role IN ('operator', 'manager')
          AND EXISTS (
              SELECT 1 FROM channel_identities bound_identity
              WHERE bound_identity.venue_id = u.venue_id
                AND bound_identity.user_id = u.id
                AND bound_identity.channel = 'WECOM'
                AND bound_identity.status = 'ACTIVE'
          )
        ORDER BY u.display_name, u.id
        """,
        (principal["venue_id"],),
    )
    return SimulatorIdentitiesResponse(identities=rows)


@router.post(
    "/simulator/messages",
    response_model=CanonicalMessageAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_simulator_message(
    body: SimulatorMessageCreateRequest,
    principal: dict[str, str] = Depends(require_auth),
    db=Depends(get_request_db),
):
    _require_simulator_operator(principal)
    queue = get_message_queue()
    if queue is None:
        raise HTTPException(status_code=503, detail="Message queue is not ready")
    try:
        accepted = await CanonicalMessageIngress(db, queue).accept(
            IngressMessage(
                channel="WECOM_SIMULATOR",
                content=body.content,
                external_message_id=body.external_message_id,
                external_conversation_id=body.external_conversation_id,
                metadata=body.metadata or {},
                attachments=body.attachments,
                selected_user_id=body.user_id,
            ),
            actor=principal,
        )
    except CanonicalIngressError as exc:
        _raise_ingress_error(exc)
    return CanonicalMessageAcceptedResponse(**accepted.__dict__)


@router.get(
    "/simulator/sessions/{session_id}/outbox",
    response_model=SimulatorOutboxResponse,
)
async def get_simulator_session_outbox(
    session_id: str,
    user_id: str = Query(..., min_length=1, max_length=64),
    principal: dict[str, str] = Depends(require_auth),
    db=Depends(get_request_db),
):
    _require_simulator_operator(principal)
    session = await db.fetch_one(
        """
        SELECT c.session_id, c.user_id
        FROM channel_conversations c
        JOIN sessions s
          ON s.session_id = c.session_id AND s.venue_id = c.venue_id
         AND s.user_id = c.user_id
        JOIN users u
          ON u.id = c.user_id AND u.venue_id = c.venue_id
        WHERE c.session_id = ? AND c.venue_id = ? AND c.user_id = ?
          AND c.channel = 'WECOM_SIMULATOR' AND c.status = 'ACTIVE'
          AND u.status = 'ACTIVE'
          AND EXISTS (
              SELECT 1 FROM channel_identities ci
              WHERE ci.venue_id = c.venue_id AND ci.user_id = c.user_id
                AND ci.channel = 'WECOM' AND ci.status = 'ACTIVE'
          )
        """,
        (session_id, principal["venue_id"], user_id),
    )
    if session is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "SIMULATOR_SESSION_NOT_FOUND",
                "message": "The selected simulator session is not available.",
            },
        )

    items = await load_simulator_outbox(
        db,
        venue_id=principal["venue_id"],
        session_id=session_id,
    )
    return SimulatorOutboxResponse(
        session_id=session_id,
        user_id=session["user_id"],
        items=items,
    )


@router.post(
    "/identities",
    response_model=ChannelIdentityResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upsert_channel_identity(
    body: ChannelIdentityCreateRequest,
    principal: dict[str, str] = Depends(require_auth),
    db=Depends(get_request_db),
):
    _require_admin(principal)
    target = await db.fetch_one(
        "SELECT id, venue_id, status FROM users WHERE id = ?",
        (body.user_id,),
    )
    if not target or target["venue_id"] != principal["venue_id"]:
        raise HTTPException(
            status_code=404,
            detail={"code": "IDENTITY_TARGET_NOT_FOUND", "message": "Employee not found."},
        )
    if body.status == "ACTIVE" and target["status"] != "ACTIVE":
        raise HTTPException(
            status_code=409,
            detail={"code": "IDENTITY_TARGET_INACTIVE", "message": "Employee is inactive."},
        )

    now = time.time()
    identity_key = "\x1f".join(
        (
            principal["venue_id"],
            body.channel,
            body.external_tenant_id,
            body.external_user_id,
        )
    )
    identity_id = str(uuid.uuid5(uuid.NAMESPACE_URL, identity_key))
    await db.execute(
        """
        INSERT INTO channel_identities (
            id, venue_id, channel, external_tenant_id, external_user_id,
            user_id, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(venue_id, channel, external_tenant_id, external_user_id)
        DO UPDATE SET user_id = excluded.user_id,
                      status = excluded.status,
                      updated_at = excluded.updated_at
        """,
        (
            identity_id,
            principal["venue_id"],
            body.channel,
            body.external_tenant_id,
            body.external_user_id,
            body.user_id,
            body.status,
            now,
            now,
        ),
    )
    row = await db.fetch_one(
        """
        SELECT id, venue_id, channel, external_tenant_id, external_user_id,
               user_id, status, created_at, updated_at
        FROM channel_identities
        WHERE venue_id = ? AND channel = ? AND external_tenant_id = ?
          AND external_user_id = ?
        """,
        (
            principal["venue_id"],
            body.channel,
            body.external_tenant_id,
            body.external_user_id,
        ),
    )
    await db.execute(
        """
        INSERT INTO audit_logs (
            venue_id, user_id, action, resource_type, resource_id,
            outcome, trace_id, metadata_json, created_at
        ) VALUES (?, ?, 'CHANNEL_IDENTITY_UPSERTED', 'channel_identity', ?,
                  'SUCCEEDED', ?, ?, ?)
        """,
        (
            principal["venue_id"],
            principal["user_id"],
            row["id"],
            uuid.uuid4().hex,
            json.dumps({"channel": body.channel, "status": body.status}),
            now,
        ),
    )
    return ChannelIdentityResponse(**row)


@router.post(
    "/wecom/messages",
    response_model=CanonicalMessageAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_wecom_message(
    body: WeComMessageCreateRequest,
    principal: dict[str, str] = Depends(require_auth),
    db=Depends(get_request_db),
):
    if principal.get("role") != "api":
        raise HTTPException(
            status_code=403,
            detail={"code": "WECOM_ADAPTER_FORBIDDEN", "message": "Channel API access is required."},
        )
    readiness = wechat_integration_readiness()
    if not readiness["configured"]:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "INTEGRATION_DISABLED",
                "message": "企业微信真实渠道尚未完成配置，消息未受理。",
                "missing": readiness["missing"],
            },
        )
    queue = get_message_queue()
    if queue is None:
        raise HTTPException(status_code=503, detail="Message queue is not ready")
    try:
        accepted = await CanonicalMessageIngress(db, queue).accept(
            IngressMessage(
                channel="WECOM",
                content=body.content,
                external_message_id=body.external_message_id,
                external_conversation_id=body.external_conversation_id,
                metadata=body.metadata or {},
                attachments=body.attachments,
                external_tenant_id=body.external_tenant_id,
                external_user_id=body.external_user_id,
            ),
            actor=principal,
        )
    except CanonicalIngressError as exc:
        _raise_ingress_error(exc)
    return CanonicalMessageAcceptedResponse(**accepted.__dict__)
