"""Execute formal unified-agent UAT steps through public HTTP interfaces."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

import httpx

from .evidence import EvidenceRun


SUPPORTED_UAT_STEPS = ("E2E-00", "E2E-01", "E2E-02")


class UATJourneyError(RuntimeError):
    """Raised when a formal UAT step cannot be executed safely."""


@dataclass(frozen=True)
class UATJourneyConfig:
    base_url: str
    admin_username: str
    admin_password: str = field(repr=False)
    timeout_seconds: float = 30.0

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> "UATJourneyConfig":
        values = os.environ if environment is None else environment
        base_url = values.get(
            "MEMORY_PALACE_UAT_BASE_URL",
            "http://localhost:8000",
        ).strip()
        admin_username = values.get("ADMIN_USERNAME", "").strip().lower()
        admin_password = _read_environment_secret(values, "ADMIN_PASSWORD")
        raw_timeout = values.get("MEMORY_PALACE_UAT_TIMEOUT_SECONDS", "30").strip()
        try:
            timeout_seconds = float(raw_timeout)
        except ValueError as exc:
            raise UATJourneyError("MEMORY_PALACE_UAT_TIMEOUT_SECONDS 必须是数字") from exc
        missing = [
            name
            for name, value in (
                ("MEMORY_PALACE_UAT_BASE_URL", base_url),
                ("ADMIN_USERNAME", admin_username),
                ("ADMIN_PASSWORD", admin_password),
            )
            if not value
        ]
        if missing:
            raise UATJourneyError("缺少 UAT 执行配置：" + ", ".join(missing))
        if len(admin_password) < 8:
            raise UATJourneyError("ADMIN_PASSWORD 长度不能少于 8 位")
        if timeout_seconds <= 0:
            raise UATJourneyError("MEMORY_PALACE_UAT_TIMEOUT_SECONDS 必须大于 0")
        return cls(
            base_url=base_url.rstrip("/"),
            admin_username=admin_username,
            admin_password=admin_password,
            timeout_seconds=timeout_seconds,
        )


def _read_environment_secret(values: Mapping[str, str], name: str) -> str:
    value = values.get(name, "")
    if value:
        return value.strip()
    secret_path = values.get(f"{name}_FILE", "").strip()
    if not secret_path:
        return ""
    try:
        return Path(secret_path).read_text(encoding="utf-8-sig").strip()
    except OSError as exc:
        raise UATJourneyError(f"无法读取 {name}_FILE 指向的密钥文件") from exc


class _FormalClient:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client
        self._access_token = ""

    async def login(self, username: str, password: str) -> dict[str, Any]:
        payload = await self.request(
            "POST",
            "/api/v1/auth/login",
            body={"username": username, "password": password},
            authenticated=False,
        )
        token = payload.get("access_token")
        principal = payload.get("user")
        if not isinstance(token, str) or not token or not isinstance(principal, dict):
            raise UATJourneyError("登录接口未返回有效管理员会话")
        self._access_token = token
        return principal

    async def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        authenticated: bool = True,
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        if authenticated:
            if not self._access_token:
                raise UATJourneyError("尚未建立管理员会话")
            headers["Authorization"] = f"Bearer {self._access_token}"
        try:
            response = await self._client.request(
                method,
                path,
                json=body,
                params=params,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise UATJourneyError(f"正式接口请求失败：{method} {path}") from exc
        if not 200 <= response.status_code < 300:
            raise UATJourneyError(f"正式接口拒绝 UAT 步骤：{method} {path} -> {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise UATJourneyError(f"正式接口返回了无法解析的响应：{method} {path}") from exc
        if not isinstance(payload, dict):
            raise UATJourneyError(f"正式接口返回格式不正确：{method} {path}")
        return payload

    async def expect_rejection(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        expected_statuses: tuple[int, ...] = (403, 404),
    ) -> dict[str, Any]:
        if not self._access_token:
            raise UATJourneyError("尚未建立管理员会话")
        try:
            response = await self._client.request(
                method,
                path,
                params=params,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {self._access_token}",
                },
            )
        except httpx.HTTPError as exc:
            raise UATJourneyError(f"正式接口请求失败：{method} {path}") from exc
        if response.status_code not in expected_statuses:
            raise UATJourneyError(f"越权请求未按预期拒绝：{method} {path} -> {response.status_code}")
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        detail = payload.get("detail") if isinstance(payload, dict) else None
        return {"status_code": response.status_code, "detail": detail}

    async def upload_simulator_attachment(
        self,
        path: Path,
        *,
        user_id: str,
    ) -> dict[str, Any]:
        if not self._access_token:
            raise UATJourneyError("尚未建立管理员会话")
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise UATJourneyError(f"无法读取 E2E-02 现场图片：{path}") from exc
        if path.suffix.lower() != ".png" or not content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise UATJourneyError("E2E-02 现场附件必须是有效 PNG 图片")
        try:
            response = await self._client.post(
                "/api/v1/channels/simulator/attachments",
                data={"user_id": user_id},
                files={"file": (path.name, content, "image/png")},
                headers={"Authorization": f"Bearer {self._access_token}"},
            )
        except httpx.HTTPError as exc:
            raise UATJourneyError("正式接口请求失败：POST /api/v1/channels/simulator/attachments") from exc
        if not 200 <= response.status_code < 300:
            raise UATJourneyError(
                "正式接口拒绝 UAT 步骤：POST " f"/api/v1/channels/simulator/attachments -> {response.status_code}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise UATJourneyError("现场附件上传接口返回了无法解析的响应") from exc
        attachment = payload.get("attachment") if isinstance(payload, dict) else None
        if not isinstance(attachment, dict):
            raise UATJourneyError("现场附件上传接口未返回附件元数据")
        return attachment


def _assertion(name: str, passed: bool, actual: Any) -> dict[str, Any]:
    return {"name": name, "passed": passed, "actual": actual}


def _dict_field(payload: Mapping[str, Any], name: str) -> dict[str, Any]:
    value = payload.get(name)
    return value if isinstance(value, dict) else {}


def _list_field(payload: Mapping[str, Any], name: str) -> list[Any]:
    value = payload.get(name)
    return value if isinstance(value, list) else []


def _record_step_result(
    run: EvidenceRun,
    step_id: str,
    *,
    passed: bool,
    evidence: Mapping[str, Any],
) -> Path:
    result_path = Path(
        run.record_step(
            step_id,
            status="PASSED" if passed else "FAILED",
            evidence=evidence,
        )
    )
    if not passed:
        raise UATJourneyError(f"{step_id} FAILED，失败证据已保留：{result_path}")
    return result_path


async def _run_e2e_00(
    api: _FormalClient,
    run: EvidenceRun,
    config: UATJourneyConfig,
) -> Path:
    principal = await api.login(config.admin_username, config.admin_password)
    probe = await api.request("POST", "/api/v1/admin/diagnostics/deepseek-probe")
    diagnostics = await api.request("GET", "/api/v1/admin/diagnostics")
    trace_id = str(probe.get("trace_id") or "")
    request_id = str(probe.get("request_id") or "")
    llm_payload = await api.request(
        "GET",
        "/api/v1/admin/llm-calls",
        params={"trace_id": trace_id},
    )
    audit_payload = await api.request(
        "GET",
        "/api/v1/admin/audit-logs",
        params={"trace_id": trace_id},
    )

    runtime = _dict_field(diagnostics, "runtime")
    required_runtime = ("app", "postgresql", "redis", "chromadb", "worker")
    runtime_statuses = {name: _dict_field(runtime, name).get("status") for name in required_runtime}
    coverage = _dict_field(diagnostics, "agent_coverage")
    deepseek = _dict_field(diagnostics, "deepseek")
    channels = _dict_field(diagnostics, "channels")
    simulator = _dict_field(channels, "wecom_simulator")
    production_channel = _dict_field(channels, "real_wecom")
    llm_calls = _list_field(llm_payload, "llm_calls")
    audits = _list_field(audit_payload, "audit_logs")
    model_call = next(
        (
            item
            for item in llm_calls
            if isinstance(item, dict) and item.get("trace_id") == trace_id and item.get("request_id") == request_id
        ),
        {},
    )
    probe_audit = next(
        (
            item
            for item in audits
            if isinstance(item, dict)
            and item.get("trace_id") == trace_id
            and item.get("action") == "DEEPSEEK_PROBE_RUN"
        ),
        {},
    )

    assertions = [
        _assertion(
            "管理员身份属于冻结 UAT 场地",
            principal.get("role") == "admin" and principal.get("venue_id") == "venue-yueshan",
            {"role": principal.get("role"), "venue_id": principal.get("venue_id")},
        ),
        _assertion(
            "正式运行依赖全部健康",
            diagnostics.get("status") == "healthy" and all(value == "healthy" for value in runtime_statuses.values()),
            {"overall": diagnostics.get("status"), "components": runtime_statuses},
        ),
        _assertion(
            "八个 Agent 已注册",
            coverage.get("status") == "healthy"
            and coverage.get("registered_agent_count") == 8
            and coverage.get("required_agent_count") == 8,
            coverage,
        ),
        _assertion(
            "DeepSeek 真实探针使用指定模型并已落库",
            probe.get("status") == "READY"
            and probe.get("provider") == "deepseek"
            and probe.get("model") == "deepseek-v4-flash"
            and probe.get("is_mock") is False
            and deepseek.get("status") == "READY"
            and deepseek.get("live_verified") is True
            and model_call.get("status") == "SUCCEEDED"
            and model_call.get("is_mock") is False,
            {
                "probe_status": probe.get("status"),
                "provider": probe.get("provider"),
                "model": probe.get("model"),
                "is_mock": probe.get("is_mock"),
                "persisted_status": model_call.get("status"),
            },
        ),
        _assertion(
            "企业内部系统接入环境已就绪",
            simulator.get("status") == "SIMULATOR_READY" and simulator.get("unmapped_active_user_count") == 0,
            simulator,
        ),
        _assertion(
            "生产外部渠道保持策略禁用且无副作用",
            production_channel.get("status") == "DISABLED_BY_POLICY"
            and production_channel.get("client_initialized") is False
            and production_channel.get("enqueue_enabled") is False
            and production_channel.get("delivery_enabled") is False,
            production_channel,
        ),
        _assertion(
            "DeepSeek 探针审计已持久化",
            probe_audit.get("outcome") == "SUCCEEDED",
            {
                "action": probe_audit.get("action"),
                "outcome": probe_audit.get("outcome"),
                "trace_id": probe_audit.get("trace_id"),
            },
        ),
    ]
    passed = all(item["passed"] for item in assertions)
    evidence = {
        "role": "刘海 / 系统管理员",
        "entrypoint": "/admin/diagnostics",
        "business_ids": {
            "venue_id": str(principal.get("venue_id") or ""),
            "trace_id": trace_id,
            "model_request_id": request_id,
        },
        "references": [
            "POST /api/v1/auth/login",
            "POST /api/v1/admin/diagnostics/deepseek-probe",
            "GET /api/v1/admin/diagnostics",
            "GET /api/v1/admin/llm-calls?trace_id={trace_id}",
            "GET /api/v1/admin/audit-logs?trace_id={trace_id}",
        ],
        "assertions": assertions,
        "model_calls": [
            {
                "provider": model_call.get("provider"),
                "model": model_call.get("model_name"),
                "is_mock": model_call.get("is_mock"),
                "request_id": model_call.get("request_id"),
                "trace_id": model_call.get("trace_id"),
                "status": model_call.get("status"),
            }
        ],
        "artifacts": {
            "runtime-diagnostics": diagnostics,
            "deepseek-probe": probe,
            "llm-call": model_call,
            "probe-audit": probe_audit,
        },
    }
    return _record_step_result(run, "E2E-00", passed=passed, evidence=evidence)


async def _run_e2e_01(
    api: _FormalClient,
    run: EvidenceRun,
    config: UATJourneyConfig,
) -> Path:
    principal = await api.login(config.admin_username, config.admin_password)
    identities_payload = await api.request("GET", "/api/v1/channels/simulator-identities")
    identities = _list_field(identities_payload, "identities")
    li_ming = next(
        (identity for identity in identities if isinstance(identity, dict) and identity.get("username") == "li-ming"),
        {},
    )
    user_id = str(li_ming.get("user_id") or "")
    session_params = {"acting_user_id": user_id}
    first_sessions = await api.request(
        "GET",
        "/api/v1/assistant/sessions",
        params=session_params,
    )
    restored_sessions = await api.request(
        "GET",
        "/api/v1/assistant/sessions",
        params=session_params,
    )
    forged_rejection = await api.expect_rejection(
        "GET",
        "/api/v1/assistant/sessions",
        params={"acting_user_id": "forged-user"},
    )
    pristine = await api.request(
        "GET",
        "/api/v1/admin/uat-pristine/venue-yueshan",
    )
    sessions = _list_field(restored_sessions, "sessions")
    process_counts = _dict_field(pristine, "process_counts")
    assertions = [
        _assertion(
            "授权演示人员属于冻结 UAT 场地",
            principal.get("role") in {"admin", "manager"} and principal.get("venue_id") == "venue-yueshan",
            {"role": principal.get("role"), "venue_id": principal.get("venue_id")},
        ),
        _assertion(
            "李明身份由服务端映射并包含完整组织信息",
            li_ming.get("display_name") == "李明"
            and li_ming.get("role") == "operator"
            and li_ming.get("venue_id") == "venue-yueshan"
            and li_ming.get("organization_name") == "悦山文旅集团"
            and li_ming.get("venue_name") == "悦山景区"
            and li_ming.get("department") == "东门运营组"
            and li_ming.get("job_title") == "东门运营员"
            and li_ming.get("wecom_binding_status") == "ACTIVE"
            and li_ming.get("status") == "ACTIVE",
            li_ming,
        ),
        _assertion(
            "刷新前后从服务端恢复相同会话集合",
            first_sessions == restored_sessions,
            {"session_count": len(sessions)},
        ),
        _assertion(
            "返回会话仅属于李明和悦山景区",
            all(
                isinstance(session, dict)
                and session.get("user_id") == user_id
                and session.get("venue_id") == "venue-yueshan"
                and session.get("channel") == "WECOM_SIMULATOR"
                for session in sessions
            ),
            {"session_count": len(sessions)},
        ),
        _assertion(
            "伪造员工身份在读取前被拒绝",
            forged_rejection.get("status_code") in {403, 404},
            forged_rejection,
        ),
        _assertion(
            "身份和会话检查未创建业务过程数据",
            pristine.get("pristine") is True
            and bool(process_counts)
            and all(value == 0 for value in process_counts.values()),
            process_counts,
        ),
    ]
    passed = bool(user_id) and all(item["passed"] for item in assertions)
    evidence = {
        "role": "李明 / 东门运营员",
        "entrypoint": "/simulator/wecom/",
        "business_ids": {
            "venue_id": str(principal.get("venue_id") or ""),
            "user_id": user_id,
        },
        "references": [
            "POST /api/v1/auth/login",
            "GET /api/v1/channels/simulator-identities",
            "GET /api/v1/assistant/sessions?acting_user_id={user_id}",
            "GET /api/v1/admin/uat-pristine/venue-yueshan",
        ],
        "assertions": assertions,
        "artifacts": {
            "server-bound-identity": li_ming,
            "initial-sessions": first_sessions,
            "restored-sessions": restored_sessions,
            "forged-identity-rejection": forged_rejection,
            "post-check-process-counts": pristine,
        },
    }
    return _record_step_result(run, "E2E-01", passed=passed, evidence=evidence)


async def _run_e2e_02(
    api: _FormalClient,
    run: EvidenceRun,
    config: UATJourneyConfig,
    attachment_path: Path,
) -> Path:
    principal = await api.login(config.admin_username, config.admin_password)
    identities_payload = await api.request("GET", "/api/v1/channels/simulator-identities")
    identities = _list_field(identities_payload, "identities")
    li_ming = next(
        (identity for identity in identities if isinstance(identity, dict) and identity.get("username") == "li-ming"),
        {},
    )
    user_id = str(li_ming.get("user_id") or "")
    if not user_id:
        raise UATJourneyError("E2E-02 无法加载李明的服务端绑定身份")

    uploaded_attachment = await api.upload_simulator_attachment(
        attachment_path,
        user_id=user_id,
    )
    attachment_id = str(uploaded_attachment.get("attachment_id") or "")
    content = (
        "12号观光车刚做开园前试车，右后轮间歇性金属摩擦声，昨晚下过大雨，"
        "车上没人。我已经把车停在维修区并断电了，下一步怎么处理？"
    )
    attachment_description = "右后轮内侧有水迹，车辆已断电，现场无人受伤"
    run_key = run.run_id.lower()
    external_message_id = f"{run_key}-e2e-02-message"
    external_conversation_id = f"{run_key}-li-ming"
    message_body: dict[str, Any] = {
        "user_id": user_id,
        "content": content,
        "external_message_id": external_message_id,
        "external_conversation_id": external_conversation_id,
        "metadata": {
            "venue_id": "forged-venue-must-be-ignored",
            "uat_run_id": run.run_id,
        },
        "attachments": [
            {
                "attachment_id": attachment_id,
                "description": attachment_description,
            }
        ],
    }
    accepted = await api.request(
        "POST",
        "/api/v1/channels/simulator/messages",
        body=message_body,
    )
    replayed = await api.request(
        "POST",
        "/api/v1/channels/simulator/messages",
        body=message_body,
    )
    message_id = str(accepted.get("message_id") or "")
    trace_id = str(accepted.get("trace_id") or "")
    session_id = str(accepted.get("session_id") or "")
    session_params = {"acting_user_id": user_id}
    session_collection = await api.request(
        "GET",
        "/api/v1/assistant/sessions",
        params=session_params,
    )
    initial_history = await api.request(
        "GET",
        f"/api/v1/assistant/sessions/{session_id}/messages",
        params=session_params,
    )
    restored_history = await api.request(
        "GET",
        f"/api/v1/assistant/sessions/{session_id}/messages",
        params=session_params,
    )
    trace = await api.request("GET", f"/api/v1/admin/traces/{trace_id}")
    audit_payload = await api.request(
        "GET",
        "/api/v1/admin/audit-logs",
        params={"trace_id": trace_id},
    )

    sessions = _list_field(session_collection, "sessions")
    matching_sessions: list[dict[str, Any]] = [
        item for item in sessions if isinstance(item, dict) and item.get("session_id") == session_id
    ]
    messages = _list_field(restored_history, "messages")
    matching_user_messages: list[dict[str, Any]] = [
        item
        for item in messages
        if isinstance(item, dict) and item.get("role") == "user" and item.get("message_id") == message_id
    ]
    restored_attachment = next(
        (
            item
            for message in matching_user_messages
            for item in _list_field(message, "attachments")
            if isinstance(item, dict) and item.get("attachment_id") == attachment_id
        ),
        {},
    )
    accepted_identity = _dict_field(accepted, "identity")
    trace_run = _dict_field(trace, "message_run")
    timeline = _list_field(trace, "timeline")
    audit_actions = {
        str(item.get("summary")) for item in timeline if isinstance(item, dict) and item.get("kind") == "AUDIT"
    }
    audit_logs = _list_field(audit_payload, "audit_logs")
    enqueue_audit = next(
        (
            item
            for item in audit_logs
            if isinstance(item, dict)
            and item.get("action") == "MESSAGE_ENQUEUED"
            and item.get("resource_id") == message_id
        ),
        {},
    )
    enqueue_metadata = _dict_field(enqueue_audit, "metadata")
    replay_ids_match = all(replayed.get(key) == accepted.get(key) for key in ("message_id", "trace_id", "session_id"))

    try:
        attachment_size = attachment_path.stat().st_size
    except OSError as exc:
        raise UATJourneyError(f"无法核对 E2E-02 现场图片：{attachment_path}") from exc
    assertions = [
        _assertion(
            "授权演示人员属于冻结 UAT 场地",
            principal.get("role") in {"admin", "manager"} and principal.get("venue_id") == "venue-yueshan",
            {"role": principal.get("role"), "venue_id": principal.get("venue_id")},
        ),
        _assertion(
            "现场 PNG 已真实上传并通过附件安全检查",
            bool(attachment_id)
            and uploaded_attachment.get("name") == attachment_path.name
            and uploaded_attachment.get("content_type") == "image/png"
            and uploaded_attachment.get("size_bytes") == attachment_size
            and uploaded_attachment.get("scan_status") == "PASSED"
            and bool(uploaded_attachment.get("external_ref")),
            uploaded_attachment,
        ),
        _assertion(
            "消息由服务端绑定李明和悦山景区并以排队状态受理",
            accepted.get("duplicate") is False
            and accepted.get("status") == "QUEUED"
            and accepted.get("channel") == "WECOM_SIMULATOR"
            and accepted.get("external_message_id") == external_message_id
            and accepted_identity.get("user_id") == user_id
            and accepted_identity.get("venue_id") == "venue-yueshan",
            {
                "duplicate": accepted.get("duplicate"),
                "status": accepted.get("status"),
                "channel": accepted.get("channel"),
                "identity": accepted_identity,
            },
        ),
        _assertion(
            "伪造场地元数据未覆盖服务端场地绑定",
            accepted_identity.get("venue_id") != message_body["metadata"]["venue_id"]
            and trace_run.get("venue_id") == "venue-yueshan",
            {
                "requested_venue_id": message_body["metadata"]["venue_id"],
                "accepted_venue_id": accepted_identity.get("venue_id"),
                "persisted_venue_id": trace_run.get("venue_id"),
            },
        ),
        _assertion(
            "相同外部消息编号重放只返回原消息、Trace 和会话",
            replayed.get("duplicate") is True and replay_ids_match,
            {
                "duplicate": replayed.get("duplicate"),
                "message_id": replayed.get("message_id"),
                "trace_id": replayed.get("trace_id"),
                "session_id": replayed.get("session_id"),
            },
        ),
        _assertion(
            "李明会话中只持久化一条业务入站消息和一个 run",
            len(matching_sessions) == 1
            and matching_sessions[0].get("user_id") == user_id
            and matching_sessions[0].get("venue_id") == "venue-yueshan"
            and matching_sessions[0].get("channel") == "WECOM_SIMULATOR"
            and matching_sessions[0].get("message_count") == 1
            and len(matching_user_messages) == 1
            and trace_run.get("message_id") == message_id
            and trace_run.get("session_id") == session_id
            and trace_run.get("external_message_id") == external_message_id,
            {
                "matching_session_count": len(matching_sessions),
                "message_count": (matching_sessions[0].get("message_count") if matching_sessions else None),
                "matching_user_message_count": len(matching_user_messages),
                "trace_message_id": trace_run.get("message_id"),
            },
        ),
        _assertion(
            "刷新后原文和附件元数据、说明、上传人及时间完整恢复",
            initial_history == restored_history
            and len(matching_user_messages) == 1
            and matching_user_messages[0].get("content") == content
            and restored_attachment.get("name") == attachment_path.name
            and restored_attachment.get("content_type") == "image/png"
            and restored_attachment.get("description") == attachment_description
            and restored_attachment.get("uploaded_by") == user_id
            and bool(restored_attachment.get("uploaded_by_name"))
            and restored_attachment.get("created_at") is not None,
            {
                "history_stable": initial_history == restored_history,
                "message_id": (matching_user_messages[0].get("message_id") if matching_user_messages else None),
                "attachment": restored_attachment,
            },
        ),
        _assertion(
            "消息创建与 Redis 入队审计均可由 Trace 读取",
            trace.get("trace_id") == trace_id
            and {"MESSAGE_RUN_CREATED", "MESSAGE_ENQUEUED"}.issubset(audit_actions)
            and enqueue_audit.get("outcome") == "SUCCEEDED"
            and bool(enqueue_metadata.get("stream_message_id")),
            {
                "trace_id": trace.get("trace_id"),
                "audit_actions": sorted(audit_actions),
                "stream_message_id": enqueue_metadata.get("stream_message_id"),
            },
        ),
    ]
    passed = all(item["passed"] for item in assertions)
    evidence = {
        "role": "李明 / 东门运营员",
        "entrypoint": "/simulator/wecom/",
        "business_ids": {
            "venue_id": "venue-yueshan",
            "user_id": user_id,
            "session_id": session_id,
            "message_id": message_id,
            "trace_id": trace_id,
            "attachment_id": attachment_id,
            "external_message_id": external_message_id,
        },
        "references": [
            "POST /api/v1/auth/login",
            "GET /api/v1/channels/simulator-identities",
            "POST /api/v1/channels/simulator/attachments",
            "POST /api/v1/channels/simulator/messages",
            "GET /api/v1/assistant/sessions?acting_user_id={user_id}",
            "GET /api/v1/assistant/sessions/{session_id}/messages",
            "GET /api/v1/admin/traces/{trace_id}",
            "GET /api/v1/admin/audit-logs?trace_id={trace_id}",
        ],
        "assertions": assertions,
        "artifacts": {
            "uploaded-attachment": uploaded_attachment,
            "accepted-message": accepted,
            "replayed-message": replayed,
            "session-list": session_collection,
            "initial-history": initial_history,
            "restored-history": restored_history,
            "trace-timeline": trace,
            "enqueue-audit": enqueue_audit,
        },
    }
    return _record_step_result(run, "E2E-02", passed=passed, evidence=evidence)


def _passed_step_ids(run: EvidenceRun) -> set[str]:
    try:
        manifest = json.loads((run.path / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UATJourneyError("UAT 证据包 manifest 无法读取") from exc
    manifest_payload = manifest if isinstance(manifest, dict) else {}
    steps = manifest_payload.get("steps")
    if not isinstance(steps, list):
        raise UATJourneyError("UAT 证据包 manifest 缺少步骤列表")
    return {str(step.get("id")) for step in steps if isinstance(step, dict) and step.get("status") == "PASSED"}


async def run_uat_steps(
    config: UATJourneyConfig,
    run: EvidenceRun,
    step_ids: Iterable[str],
    *,
    client: httpx.AsyncClient | None = None,
    attachment_path: Path | None = None,
) -> list[Path]:
    """Execute selected UAT steps in order and record immutable evidence."""

    requested = list(step_ids)
    supported = set(SUPPORTED_UAT_STEPS)
    unsupported = [step_id for step_id in requested if step_id not in supported]
    if unsupported:
        raise UATJourneyError("尚未支持的 UAT 步骤：" + "、".join(unsupported))
    owns_client = client is None
    active_client = client or httpx.AsyncClient(
        base_url=config.base_url.rstrip("/"),
        timeout=config.timeout_seconds,
        follow_redirects=True,
    )
    api = _FormalClient(active_client)
    try:
        recorded: list[Path] = []
        for step_id in requested:
            if step_id == "E2E-00":
                recorded.append(await _run_e2e_00(api, run, config))
            elif step_id == "E2E-01":
                if "E2E-00" not in _passed_step_ids(run):
                    raise UATJourneyError("E2E-01 要求同一证据包中的 E2E-00 已通过")
                recorded.append(await _run_e2e_01(api, run, config))
            elif step_id == "E2E-02":
                if "E2E-01" not in _passed_step_ids(run):
                    raise UATJourneyError("E2E-02 要求同一证据包中的 E2E-01 已通过")
                if attachment_path is None:
                    raise UATJourneyError("E2E-02 必须显式提供现场 PNG 附件路径")
                recorded.append(await _run_e2e_02(api, run, config, attachment_path.resolve()))
        return recorded
    finally:
        if owns_client:
            await active_client.aclose()
