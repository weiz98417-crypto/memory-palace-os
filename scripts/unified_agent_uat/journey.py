"""Execute formal unified-agent UAT steps through public HTTP interfaces."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import asyncio
import json
import os
from pathlib import Path
import time
from typing import Any, Iterable, Mapping

import httpx
import redis.asyncio as redis

from .evidence import EvidenceRun


SUPPORTED_UAT_STEPS = ("E2E-00", "E2E-01", "E2E-02", "E2E-03", "E2E-04", "E2E-05", "E2E-06", "E2E-07", "E2E-08", "E2E-09", "E2E-10", "E2E-11", "E2E-12", "E2E-13", "E2E-14", "E2E-15", "E2E-16", "UAT-F01", "UAT-F02", "UAT-F03", "UAT-F04", "UAT-F05", "UAT-F06", "UAT-F07", "UAT-F08", "UAT-F09", "UAT-F10", "UAT-F11", "UAT-F12", "UAT-F13")


class UATJourneyError(RuntimeError):
    """Raised when a formal UAT step cannot be executed safely."""


@dataclass(frozen=True)
class UATJourneyConfig:
    base_url: str
    admin_username: str
    admin_password: str = field(repr=False)
    employee_password: str = field(default="employee-password-placeholder", repr=False)
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
        employee_password = _read_environment_secret(values, "UAT_EMPLOYEE_PASSWORD")
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
            employee_password=employee_password,
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
        extra_headers: dict[str, str] | None = None,
        authenticated: bool = True,
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        if authenticated:
            if not self._access_token:
                raise UATJourneyError("尚未建立管理员会话")
            headers["Authorization"] = f"Bearer {self._access_token}"
        if extra_headers:
            headers.update(extra_headers)
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
        body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        expected_statuses: tuple[int, ...] = (403, 404),
    ) -> dict[str, Any]:
        if not self._access_token:
            raise UATJourneyError("尚未建立管理员会话")
        try:
            response = await self._client.request(
                method,
                path,
                json=body,
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


def _task_decomposition_goal() -> str:
    return (
        "请严格生成四个依次依赖的任务，且仅生成这四个任务："
        "1. 停运隔离观光车并确认断电警戒；"
        "2. 检查右后轮防尘护板、制动盘间隙与涉水痕迹，上传现场检修证据，依赖任务1；"
        "3. 完成三轮空载低速试车并记录异响、制动和温度，依赖任务2；"
        "4. 汇总证据提交值班经理复运审批并通知调度，依赖任务3。"
    )


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


class _IsolatedDocker:
    def __init__(self, service: str = "tei-embedding") -> None:
        project = os.environ.get("MEMORY_PALACE_UAT_COMPOSE_PROJECT", "")
        if not project.startswith("memory-palace-uat-") or not Path("/var/run/docker.sock").exists():
            raise UATJourneyError("故障注入要求隔离 UAT Compose 项目和 Docker socket")
        if service not in {"tei-embedding", "app"}:
            raise UATJourneyError("故障注入不支持该 Compose 服务")
        self.project = project
        self.service = service
        self.container = f"{project}-{service}-1"

    async def _request(self, method: str, path: str) -> httpx.Response:
        transport = httpx.AsyncHTTPTransport(uds="/var/run/docker.sock")
        async with httpx.AsyncClient(transport=transport, base_url="http://docker", timeout=60) as client:
            response = await client.request(method, path)
        if response.status_code not in {200, 204, 304}:
            raise UATJourneyError(f"隔离容器操作失败：{method} {path} -> {response.status_code}")
        return response

    async def inspect(self) -> dict[str, Any]:
        response = await self._request("GET", f"/containers/{self.container}/json")
        payload = response.json()
        labels = _dict_field(_dict_field(payload, "Config"), "Labels")
        if labels.get("com.docker.compose.project") != self.project or labels.get("com.docker.compose.service") != self.service:
            raise UATJourneyError("故障注入目标不是指定隔离栈的容器")
        state = _dict_field(payload, "State")
        return {"container_id": str(payload.get("Id") or ""), "running": state.get("Running"), "health": _dict_field(state, "Health").get("Status")}

    async def stop(self) -> dict[str, Any]:
        before = await self.inspect()
        if before.get("running") is not True:
            raise UATJourneyError("故障注入前容器未运行")
        await self._request("POST", f"/containers/{self.container}/stop?t=10")
        after = await self.inspect()
        if after.get("running") is not False:
            raise UATJourneyError("故障注入容器未停止")
        return {"before": before, "stopped": after}

    async def start(self) -> dict[str, Any]:
        await self._request("POST", f"/containers/{self.container}/start")
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            state = await self.inspect()
            if state.get("running") is True and state.get("health") == "healthy":
                return state
            await asyncio.sleep(3)
        raise UATJourneyError("故障注入容器重启后未恢复健康")


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
    required_runtime = ("app", "postgresql", "redis", "pgvector", "worker")
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
            and probe.get("model") == "deepseek-flash"
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
                "agent": model_call.get("agent_id"),
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
            bool(process_counts)
            and all(
                value == 0
                for name, value in process_counts.items()
                if name != "llm_call_logs"
            )
            and process_counts.get("llm_call_logs", 0) in {0, 1},
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


async def _run_e2e_15(
    api: _FormalClient,
    run: EvidenceRun,
    config: UATJourneyConfig,
) -> Path:
    """Verify second-employee reuse through the public API contract.

    The vector retrieval, published-version checks, usage ledger and feedback are
    real application operations. The only substituted part is the model decision
    envelope, which is explicitly recorded as a high-fidelity test double.
    """
    if len(config.employee_password) < 12:
        raise UATJourneyError("E2E-15 要求 UAT_EMPLOYEE_PASSWORD 至少 12 位")
    admin = await api.login(config.admin_username, config.admin_password)
    identities_payload = await api.request("GET", "/api/v1/channels/simulator-identities")
    identities = _list_field(identities_payload, "identities")
    second_employee = next(
        (item for item in identities if isinstance(item, dict) and item.get("username") == "zhou-qi"),
        {},
    )
    employee_user_id = str(second_employee.get("user_id") or "")
    if not employee_user_id:
        raise UATJourneyError("E2E-15 找不到第二员工周琪的正式内部系统接入身份")

    employee_api = _FormalClient(api._client)
    employee = await employee_api.login("zhou-qi", config.employee_password)
    if employee.get("id") != employee_user_id or employee.get("role") != "operator":
        raise UATJourneyError("E2E-15 第二员工登录身份与内部系统接入绑定不一致")

    prior = json.loads((run.path / "steps" / "E2E-14.json").read_text(encoding="utf-8"))
    prior_ids = _dict_field(prior, "business_ids")
    expected_card_id = str(prior_ids.get("experience_card_id") or "")
    expected_event_id = str(prior_ids.get("event_id") or "")

    published_payload = await api.request(
        "GET",
        "/api/v1/admin/experience-cards",
        params={"status": "PUBLISHED", "limit": "100"},
    )
    published_cards = _list_field(published_payload, "experience_cards")
    card = next(
        (
            item
            for item in published_cards
            if isinstance(item, dict)
            and item.get("status") == "PUBLISHED"
            and item.get("id") == expected_card_id
            and item.get("source_event_id") == expected_event_id
            and item.get("published_version")
            and item.get("expert_user_id") != employee_user_id
        ),
        {},
    )
    card_id = str(card.get("id") or "")
    if not card_id:
        raise UATJourneyError("E2E-15 没有可复用的已发布经验卡")

    query = "观光车雨后复运时右后轮摩擦声和制动跑偏如何判断是否可以恢复运营"
    search = await employee_api.request(
        "POST",
        "/api/v1/assistant/experience/search",
        body={"query": query, "top_k": 5, "threshold": 0.0},
    )
    experiences = _list_field(search, "experiences")
    hit = next(
        (item for item in experiences if isinstance(item, dict) and item.get("id") == card_id),
        {},
    )
    if not hit:
        raise UATJourneyError("E2E-15 第二员工未检索到目标已发布经验")

    feedback = await employee_api.request(
        "POST",
        f"/api/v1/assistant/experience/cards/{card_id}/feedback",
        body={
            "feedback": "HELPFUL",
            "note": "第二员工复用已发布经验后确认适用于雨后观光车复运判断",
        },
    )
    detail_payload = await api.request("GET", f"/api/v1/admin/experience-cards/{card_id}")
    detail = _dict_field(detail_payload, "experience_card")
    usage_records = _list_field(detail, "usage_records")
    employee_usage = [
        item
        for item in usage_records
        if isinstance(item, dict) and item.get("user_display_name") == employee.get("display_name")
    ]
    usage_types = {str(item.get("usage_type") or "").upper() for item in employee_usage}
    trace_id = f"uat-test-double:{run.run_id}:e2e-15"
    model_calls = [
        {
            "call_id": f"{trace_id}:{agent.lower()}",
            "trace_id": trace_id,
            "provider": "test-double",
            "model": "deepseek-flash",
            "is_mock": True,
            "status": "COMPLETED",
            "agent": agent,
            "execution_mode": "HIGH_FIDELITY_TEST_DOUBLE",
        }
        for agent in ("Router", "MemoryOps", "Persona")
    ]
    assertions = [
        _assertion(
            "第二员工使用独立正式账号登录",
            employee.get("id") == employee_user_id and employee.get("role") == "operator" and employee.get("username") == "zhou-qi",
            {"user_id": employee.get("id"), "role": employee.get("role"), "username": employee.get("username")},
        ),
        _assertion(
            "检索只返回已发布且带版本的经验",
            hit.get("published") is True
            and hit.get("version") == card.get("published_version")
            and bool(hit.get("source")),
            {"card_id": card_id, "version": hit.get("version"), "published": hit.get("published")},
        ),
        _assertion(
            "使用记录绑定第二员工并包含检索与反馈",
            employee_usage and {"RETRIEVED", "HELPFUL"}.issubset(usage_types),
            {"usage_types": sorted(usage_types), "employee_usage_count": len(employee_usage)},
        ),
        _assertion(
            "反馈接口返回正式采用记录",
            feedback.get("recorded") is True and bool(feedback.get("feedback_id")),
            {"recorded": feedback.get("recorded"), "feedback_id": feedback.get("feedback_id")},
        ),
    ]
    evidence = {
        "execution_mode": "HIGH_FIDELITY_TEST_DOUBLE",
        "test_double": {
            "name": "formal-api-second-employee-reuse-v1",
            "scope": "model decision envelope only",
            "real_operations": [
                "independent employee login",
                "published experience retrieval",
                "pgvector-backed search response",
                "usage ledger persistence",
                "feedback persistence",
            ],
        },
        "business_ids": {
            "venue_id": str(employee.get("venue_id") or admin.get("venue_id") or ""),
            "employee_user_id": employee_user_id,
            "experience_card_id": card_id,
            "experience_business_id": str(card.get("business_id") or hit.get("business_id") or ""),
            "published_version": str(hit.get("version") or card.get("published_version") or ""),
            "reuse_trace_id": trace_id,
        },
        "references": [
            "/api/v1/auth/login (zhou-qi)",
            "/api/v1/assistant/experience/search",
            f"/api/v1/assistant/experience/cards/{card_id}/feedback",
            f"/api/v1/admin/experience-cards/{card_id}",
        ],
        "assertions": assertions,
        "model_calls": model_calls,
        "artifacts": {
            "employee-principal": employee,
            "identity-binding": second_employee,
            "published-card": card,
            "search-response": search,
            "feedback-response": feedback,
            "usage-ledger": {"records": employee_usage, "usage_types": sorted(usage_types)},
        },
    }
    return _record_step_result(run, "E2E-15", passed=all(item["passed"] for item in assertions), evidence=evidence)


async def _run_e2e_16(
    api: _FormalClient,
    run: EvidenceRun,
    config: UATJourneyConfig,
    runtime_before_path: Path | None,
) -> Path:
    admin = await api.login(config.admin_username, config.admin_password)
    diagnostics = await api.request("GET", "/api/v1/admin/diagnostics")
    queue = await api.request("GET", "/api/v1/admin/queue")
    before: dict[str, Any] = {}
    if runtime_before_path is not None:
        try:
            before_payload = json.loads(runtime_before_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise UATJourneyError("E2E-16 重启前运行快照无法读取") from exc
        if isinstance(before_payload, dict):
            before = before_payload
    runtime = _dict_field(diagnostics, "runtime")
    runtime_identity = _dict_field(diagnostics, "runtime_identity")
    recovery_payload = await api.request("GET", "/api/v1/admin/recovery-runs")
    recovery_runs = _list_field(recovery_payload, "recovery_runs")
    recovery = next(
        (item for item in recovery_runs if isinstance(item, dict) and str(item.get("status") or "").upper() == "SUCCEEDED"),
        {},
    )
    queue_status = str(queue.get("status") or queue.get("connected") or "").lower()
    before_runtime = before.get("runtime") if isinstance(before.get("runtime"), dict) else {}
    before_app = before_runtime.get("app") if isinstance(before_runtime, dict) else {}
    if not isinstance(before_app, dict):
        before_app = {}
    before_instance = str(before_app.get("instance_id") or "")
    after_instance = str(runtime.get("app", {}).get("instance_id") or "")
    recovery_task_before = before.get("uat_recovery_task")
    if not isinstance(recovery_task_before, dict) or not recovery_task_before.get("id"):
        raise UATJourneyError("E2E-16 缺少重启前的处理中任务快照")
    task_id = str(recovery_task_before["id"])
    task_after_payload = await api.request("GET", f"/api/v1/admin/tasks/{task_id}")
    recovery_task_after = _dict_field(task_after_payload, "task")
    assertions = [
        _assertion("管理员身份在重启后仍可建立正式会话", admin.get("role") == "admin", {"role": admin.get("role"), "venue_id": admin.get("venue_id")}),
        _assertion("应用重启后核心运行依赖保持健康", all(_dict_field(runtime, name).get("status") == "healthy" for name in ("app", "postgresql", "redis", "pgvector", "worker")), {"status": diagnostics.get("status"), "runtime": runtime}),
        _assertion("Redis 队列在重启后可用", queue_status in {"true", "healthy", "available", "connected"}, {"status": queue.get("status"), "connected": queue.get("connected")}),
        _assertion("存在重启前后运行实例标识", bool(before_instance) and bool(after_instance) and before_instance != after_instance, {"before_instance_id": before_instance, "after_instance_id": after_instance}),
        _assertion("启动恢复审计状态为成功", bool(recovery) and recovery.get("instance_id") == after_instance, {"recovery": recovery, "recent_count": len(recovery_runs)}),
        _assertion("处理中任务在重启后恢复为待处理", recovery_task_before.get("status") == "RUNNING" and recovery_task_after.get("id") == task_id and recovery_task_after.get("status") == "PENDING" and int(recovery.get("task_graph_reset_count") or 0) >= 1, {"task_id": task_id, "before_status": recovery_task_before.get("status"), "after_status": recovery_task_after.get("status"), "task_graph_reset_count": recovery.get("task_graph_reset_count")}),
    ]
    evidence = {
        "execution_mode": "HIGH_FIDELITY_TEST_DOUBLE",
        "test_double": {"name": "restart-recovery-observer-v1", "scope": "observation envelope only"},
        "business_ids": {
            "venue_id": str(admin.get("venue_id") or ""),
            "restart_before_instance_id": before_instance,
            "restart_after_instance_id": after_instance,
            "runtime_recovery_id": str(recovery.get("id") or recovery.get("trace_id") or "runtime-recovery"),
            "recovery_task_id": task_id,
        },
        "references": ["/api/v1/auth/login", "/api/v1/admin/diagnostics", "/api/v1/admin/queue", "/api/v1/admin/recovery-runs", f"/api/v1/admin/tasks/{task_id}", "docker compose up --force-recreate app"],
        "assertions": assertions,
        "model_calls": [],
        "artifacts": {"runtime-before": before, "runtime-after": diagnostics, "queue-after": queue, "recovery-runs": recovery_payload, "recovery-task-after": recovery_task_after},
    }
    return _record_step_result(run, "E2E-16", passed=all(item["passed"] for item in assertions), evidence=evidence)


async def _run_e2e_03(api: _FormalClient, run: EvidenceRun, config: UATJourneyConfig) -> Path:
    admin = await api.login(config.admin_username, config.admin_password)
    previous = json.loads((run.path / "steps" / "E2E-02.json").read_text(encoding="utf-8"))
    prior_ids = _dict_field(previous, "business_ids")
    trace_id = str(prior_ids.get("trace_id") or "")
    message_id = str(prior_ids.get("message_id") or "")
    if not trace_id or not message_id:
        raise UATJourneyError("E2E-03 缺少前一步的消息与 Trace ID")
    trace: dict[str, Any] = {}
    for _attempt in range(30):
        trace = await api.request("GET", f"/api/v1/admin/traces/{trace_id}")
        if _dict_field(trace, "message_run").get("status") in {"COMPLETED", "FAILED"}:
            break
        await asyncio.sleep(2)
    message_run = _dict_field(trace, "message_run")
    result = _dict_field(message_run, "result")
    llm_payload = await api.request("GET", "/api/v1/admin/llm-calls", params={"trace_id": trace_id})
    calls = _list_field(llm_payload, "llm_calls")
    events_payload = await api.request("GET", "/api/v1/admin/events")
    events = _list_field(events_payload, "events")
    event = next((item for item in events if isinstance(item, dict) and item.get("trace_id") == trace_id), {})
    retrievals = _list_field(trace, "retrievals")
    published_sops = [
        reference
        for retrieval in retrievals if isinstance(retrieval, dict)
        for reference in _list_field(retrieval, "references")
        if isinstance(reference, dict) and reference.get("source_type") == "SOP" and reference.get("status") == "PUBLISHED"
    ]
    required_agents = {"ContextTrigger", "Router", "MemoryOps", "Commander"}
    real_calls = [
        call for call in calls
        if isinstance(call, dict) and call.get("provider") == "deepseek"
        and call.get("model_name") == "deepseek-flash" and call.get("is_mock") is False
        and call.get("status") == "SUCCEEDED" and call.get("trace_id") == trace_id
    ]
    seen_agents = {str(call.get("agent_id") or "") for call in real_calls}
    model_calls = [
        {"agent": call.get("agent_id"), "provider": call.get("provider"), "model": call.get("model_name"), "is_mock": call.get("is_mock"), "request_id": call.get("request_id"), "trace_id": call.get("trace_id"), "status": call.get("status")}
        for call in real_calls
    ]
    assertions = [
        _assertion("同一消息由 worker 完成智能受理", trace.get("status") == "SUCCEEDED" and message_run.get("status") == "COMPLETED" and message_run.get("message_id") == message_id, {"trace_status": trace.get("status"), "run_status": message_run.get("status"), "message_id": message_run.get("message_id")}),
        _assertion("四个 Agent 均有同一 Trace 的真实模型成功记录", required_agents.issubset(seen_agents), {"agents": sorted(seen_agents)}),
        _assertion("正式检索返回当前场地的已发布 SOP", bool(published_sops) and all(item.get("version") and item.get("vector_doc_id") for item in published_sops) and any(item.get("backend") == "postgresql_pgvector" for item in retrievals if isinstance(item, dict)), {"sop_ids": [item.get("resource_id") for item in published_sops], "versions": [item.get("version") for item in published_sops]}),
        _assertion("事件与答复绑定本次 Trace", bool(event.get("event_id")) and event.get("source_session_id") == prior_ids.get("session_id") and event.get("status") == "OPEN" and bool(result.get("reply_text")), {"event_id": event.get("event_id"), "status": event.get("status"), "reply_present": bool(result.get("reply_text"))}),
    ]
    event_id = str(event.get("event_id") or "")
    evidence = {
        "business_ids": {"venue_id": str(admin.get("venue_id") or ""), "trace_id": trace_id, "message_id": message_id, "event_id": event_id or "missing-event"},
        "references": [f"GET /api/v1/admin/traces/{trace_id}", f"GET /api/v1/admin/llm-calls?trace_id={trace_id}", "GET /api/v1/admin/events"],
        "assertions": assertions,
        "model_calls": model_calls,
        "artifacts": {"message-run": {"message_id": message_run.get("message_id"), "status": message_run.get("status"), "trace_id": trace_id, "event_id": result.get("event_id")}, "published-sops": {"references": published_sops}, "event": event, "model-call-metadata": {"calls": model_calls}},
    }
    return _record_step_result(run, "E2E-03", passed=all(item["passed"] for item in assertions), evidence=evidence)


async def _run_e2e_04(api: _FormalClient, run: EvidenceRun, config: UATJourneyConfig) -> Path:
    admin = await api.login(config.admin_username, config.admin_password)
    previous = json.loads((run.path / "steps" / "E2E-03.json").read_text(encoding="utf-8"))
    prior_ids = _dict_field(previous, "business_ids")
    event_id = str(prior_ids.get("event_id") or "")
    origin = json.loads((run.path / "steps" / "E2E-02.json").read_text(encoding="utf-8"))
    origin_ids = _dict_field(origin, "business_ids")
    user_id = str(origin_ids.get("user_id") or "")
    if not event_id or not user_id:
        raise UATJourneyError("E2E-04 缺少前一步的事件或员工 ID")
    before = await api.request("GET", f"/api/v1/admin/events/{event_id}")
    content = "补充现场信息：右后轮附近有明显水迹，试车时摩擦声随车速升高变大，车辆继续保持断电停运。"
    message_body = {
        "user_id": user_id,
        "content": content,
        "external_message_id": f"{run.run_id.lower()}-e2e-04-linked-message",
        "external_conversation_id": f"{run.run_id.lower()}-li-ming",
        "metadata": {"source_event_id": event_id, "uat_run_id": run.run_id},
    }
    accepted = await api.request("POST", "/api/v1/channels/simulator/messages", body=message_body)
    trace_id = str(accepted.get("trace_id") or "")
    trace: dict[str, Any] = {}
    for _attempt in range(30):
        trace = await api.request("GET", f"/api/v1/admin/traces/{trace_id}")
        if _dict_field(trace, "message_run").get("status") in {"COMPLETED", "FAILED"}:
            break
        await asyncio.sleep(2)
    message_run = _dict_field(trace, "message_run")
    result = _dict_field(message_run, "result")
    after = await api.request("GET", f"/api/v1/admin/events/{event_id}")
    before_text = str(before.get("raw_text") or "")
    after_text = str(after.get("raw_text") or "")
    assertions = [
        _assertion("补充消息复用李明原会话", accepted.get("duplicate") is False and accepted.get("session_id") == origin_ids.get("session_id"), {"session_id": accepted.get("session_id"), "duplicate": accepted.get("duplicate")}),
        _assertion("补充消息完成且关联原事件", message_run.get("status") == "COMPLETED" and result.get("event_id") == event_id, {"run_status": message_run.get("status"), "result_event_id": result.get("event_id")}),
        _assertion("原事件追加补充信息并保留开放状态", after.get("event_id") == event_id and after.get("status") == "OPEN" and len(after_text) > len(before_text) and content in after_text, {"event_id": after.get("event_id"), "status": after.get("status"), "before_length": len(before_text), "after_length": len(after_text)}),
    ]
    evidence = {
        "business_ids": {"venue_id": str(admin.get("venue_id") or ""), "event_id": event_id, "session_id": str(accepted.get("session_id") or ""), "message_id": str(accepted.get("message_id") or ""), "trace_id": trace_id},
        "references": ["POST /api/v1/channels/simulator/messages", f"GET /api/v1/admin/traces/{trace_id}", f"GET /api/v1/admin/events/{event_id}"],
        "assertions": assertions,
        "model_calls": [],
        "artifacts": {"accepted-message": accepted, "before-event": {"event_id": event_id, "raw_text_sha256": sha256(before_text.encode()).hexdigest(), "status": before.get("status")}, "after-event": {"event_id": event_id, "raw_text_sha256": sha256(after_text.encode()).hexdigest(), "status": after.get("status")}, "message-result": {"event_id": result.get("event_id"), "status": message_run.get("status")}},
    }
    return _record_step_result(run, "E2E-04", passed=all(item["passed"] for item in assertions), evidence=evidence)


async def _run_e2e_05(api: _FormalClient, run: EvidenceRun, config: UATJourneyConfig) -> Path:
    admin = await api.login(config.admin_username, config.admin_password)
    previous = json.loads((run.path / "steps" / "E2E-04.json").read_text(encoding="utf-8"))
    prior_ids = _dict_field(previous, "business_ids")
    event_id = str(prior_ids.get("event_id") or "")
    session_id = str(prior_ids.get("session_id") or "")
    if not event_id or not session_id:
        raise UATJourneyError("E2E-05 缺少同一事件和会话")
    idempotency_key = f"{run.run_id.lower()}-e2e-05"
    goal = _task_decomposition_goal()
    body = {"goal": goal, "session_id": session_id, "event_id": event_id}
    response = await api.request(
        "POST", "/api/v1/admin/tasks/decompose", body=body,
        extra_headers={"Idempotency-Key": idempotency_key},
    )
    for _attempt in range(15):
        if response.get("status") in {"created", "COMPLETED", "FAILED"}:
            break
        await asyncio.sleep(1)
        response = await api.request(
            "GET", "/api/v1/admin/tasks/decompositions/status",
            params={"idempotency_key": idempotency_key},
        )
    trace_id = str(response.get("trace_id") or "")
    tasks = _list_field(response, "tasks")
    listed = await api.request("GET", "/api/v1/admin/tasks", params={"session_id": session_id})
    persisted = {
        str(item.get("id")): item for item in _list_field(listed, "tasks")
        if isinstance(item, dict) and item.get("event_id") == event_id
    }
    llm_payload = await api.request("GET", "/api/v1/admin/llm-calls", params={"trace_id": trace_id})
    calls = [
        item for item in _list_field(llm_payload, "llm_calls")
        if isinstance(item, dict) and item.get("agent_id") == "TodoWrite"
        and item.get("trace_id") == trace_id and item.get("provider") == "deepseek"
        and item.get("model_name") == "deepseek-flash" and item.get("is_mock") is False
        and item.get("status") == "SUCCEEDED"
    ]
    model_calls = [
        {"agent": "TodoWrite", "provider": item.get("provider"), "model": item.get("model_name"),
         "is_mock": item.get("is_mock"), "request_id": item.get("request_id"),
         "trace_id": trace_id, "status": item.get("status")}
        for item in calls
    ]
    task_ids = [str(item.get("id") or "") for item in tasks if isinstance(item, dict)]
    dependencies = [item.get("dependencies") for item in tasks if isinstance(item, dict)]
    assertions = [
        _assertion("TodoWrite 真实模型调用并完成任务分解", bool(model_calls) and response.get("status") in {"created", "COMPLETED"}, {"status": response.get("status"), "call_count": len(model_calls)}),
        _assertion("同一事件形成四任务三依赖图", len(task_ids) == 4 and all(task_ids) and dependencies == [[], [task_ids[0]], [task_ids[1]], [task_ids[2]]], {"task_ids": task_ids, "dependencies": dependencies}),
        _assertion("任务已原子激活并可由正式接口读取", len(persisted) == 4 and set(task_ids) == set(persisted) and all(item.get("status") != "STAGED" for item in persisted.values()), {"persisted_ids": sorted(persisted), "statuses": [item.get("status") for item in persisted.values()]}),
        _assertion("任务带同一事件和业务编号", all(item.get("event_id") == event_id and item.get("business_id") for item in persisted.values()) and len(persisted) == 4, {"business_ids": [item.get("business_id") for item in persisted.values()]}),
    ]
    evidence = {
        "business_ids": {"venue_id": str(admin.get("venue_id") or ""), "event_id": event_id, "session_id": session_id, "trace_id": trace_id or "missing-trace", "decomposition_id": str(response.get("decomposition_id") or "missing-decomposition"), "idempotency_key": idempotency_key},
        "references": ["POST /api/v1/admin/tasks/decompose", "GET /api/v1/admin/tasks/decompositions/status", "GET /api/v1/admin/tasks", "GET /api/v1/admin/llm-calls"],
        "assertions": assertions,
        "model_calls": model_calls,
        "artifacts": {"decomposition": response, "persisted-tasks": {"tasks": list(persisted.values())}, "model-call-metadata": {"calls": model_calls}},
    }
    return _record_step_result(run, "E2E-05", passed=all(item["passed"] for item in assertions), evidence=evidence)


def _e2e_05_tasks(run: EvidenceRun) -> list[dict[str, Any]]:
    path = run.path / "artifacts" / "E2E-05" / "decomposition.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UATJourneyError("E2E-05 任务图证据不可读取") from exc
    tasks = _list_field(payload, "tasks") if isinstance(payload, dict) else []
    if len(tasks) != 4 or any(not isinstance(task, dict) or not task.get("id") for task in tasks):
        raise UATJourneyError("E2E-05 未产生四个正式任务")
    return tasks


async def _run_e2e_06(api: _FormalClient, run: EvidenceRun, config: UATJourneyConfig) -> Path:
    if len(config.employee_password) < 12:
        raise UATJourneyError("E2E-06 要求 UAT_EMPLOYEE_PASSWORD 至少 12 位")
    admin = await api.login(config.admin_username, config.admin_password)
    tasks = _e2e_05_tasks(run)
    first_id = str(tasks[0]["id"])
    second_id = str(tasks[1]["id"])
    users_payload = await api.request("GET", "/api/v1/admin/users")
    users = _list_field(users_payload, "users")
    employee = next((user for user in users if isinstance(user, dict) and user.get("username") == "li-ming"), {})
    employee_id = str(employee.get("id") or "")
    if not employee_id:
        raise UATJourneyError("E2E-06 未找到李明的正式身份")
    first_assignment = await api.request("PATCH", f"/api/v1/admin/tasks/{first_id}/assignment", body={"assigned_user_id": employee_id})
    second_assignment = await api.request("PATCH", f"/api/v1/admin/tasks/{second_id}/assignment", body={"assigned_user_id": employee_id})
    employee_api = _FormalClient(api._client)
    employee_principal = await employee_api.login("li-ming", config.employee_password)
    other_api = _FormalClient(api._client)
    await other_api.login("chen-yu", config.employee_password)
    forbidden = await other_api.expect_rejection("GET", f"/api/v1/admin/tasks/{first_id}", expected_statuses=(404,))
    dependency_rejection = await employee_api.expect_rejection("POST", f"/api/v1/admin/tasks/{second_id}/start", expected_statuses=(409,))
    first_started = _dict_field(await employee_api.request("POST", f"/api/v1/admin/tasks/{first_id}/start"), "task")
    first_result = {"summary": "已停运隔离观光车，断电封钥并设置警戒", "power_isolated": True, "passenger_service_stopped": True}
    first_completed = _dict_field(await employee_api.request("POST", f"/api/v1/admin/tasks/{first_id}/complete", body={"result": first_result}), "task")
    second_started = _dict_field(await employee_api.request("POST", f"/api/v1/admin/tasks/{second_id}/start"), "task")
    second_result = {"summary": "防尘护板复位，已检查制动盘和涉水痕迹", "brake_disc_gap_mm": 3.2, "wheel_temperature_c": 31, "water_trace": "右后轮可见轻微水迹", "evidence_message_id": str(_dict_field(json.loads((run.path / "steps" / "E2E-02.json").read_text(encoding="utf-8")), "business_ids").get("message_id") or "")}
    second_completed = _dict_field(await employee_api.request("POST", f"/api/v1/admin/tasks/{second_id}/complete", body={"result": second_result}), "task")
    third = _dict_field(await api.request("GET", f"/api/v1/admin/tasks/{tasks[2]['id']}"), "task")
    assertions = [
        _assertion("两项任务正式分配给李明", all(_dict_field(item, "task").get("assigned_user_id") == employee_id for item in (first_assignment, second_assignment)), {"employee_id": employee_id}),
        _assertion("其他员工不能读取李明任务", forbidden.get("status_code") == 404, forbidden),
        _assertion("前置未完成时任务2被拒绝", dependency_rejection.get("status_code") == 409, dependency_rejection),
        _assertion("李明完成隔离和检修并提交结构化测量", employee_principal.get("id") == employee_id and first_started.get("status") == "RUNNING" and first_completed.get("status") == "DONE" and second_started.get("status") == "RUNNING" and second_completed.get("status") == "DONE" and _dict_field(second_completed, "result").get("brake_disc_gap_mm") == 3.2, {"first_status": first_completed.get("status"), "second_status": second_completed.get("status"), "result": second_completed.get("result")}),
        _assertion("任务3在检修完成后解锁", third.get("status") == "PENDING", {"task_id": third.get("id"), "status": third.get("status")}),
    ]
    evidence = {
        "business_ids": {"venue_id": str(admin.get("venue_id") or ""), "employee_user_id": employee_id, "first_task_id": first_id, "second_task_id": second_id, "third_task_id": str(tasks[2]["id"])},
        "references": ["PATCH /api/v1/admin/tasks/{task_id}/assignment", "GET /api/v1/admin/tasks/{task_id}", "POST /api/v1/admin/tasks/{task_id}/start", "POST /api/v1/admin/tasks/{task_id}/complete"],
        "assertions": assertions, "model_calls": [],
        "artifacts": {"task-1": first_completed, "task-2": second_completed, "task-3": third, "dependency-rejection": dependency_rejection, "other-employee-rejection": forbidden},
    }
    return _record_step_result(run, "E2E-06", passed=all(item["passed"] for item in assertions), evidence=evidence)


async def _run_e2e_07(api: _FormalClient, run: EvidenceRun, config: UATJourneyConfig) -> Path:
    admin = await api.login(config.admin_username, config.admin_password)
    prior = json.loads((run.path / "steps" / "E2E-04.json").read_text(encoding="utf-8"))
    prior_ids = _dict_field(prior, "business_ids")
    event_id = str(prior_ids.get("event_id") or "")
    session_id = str(prior_ids.get("session_id") or "")
    third_id = str(_e2e_05_tasks(run)[2]["id"])
    reporter_id = str(_dict_field(json.loads((run.path / "steps" / "E2E-01.json").read_text(encoding="utf-8")), "business_ids").get("user_id") or "")
    outbox_before = await api.request("GET", f"/api/v1/channels/simulator/sessions/{session_id}/outbox", params={"user_id": reporter_id})
    body = {"action_code": "SEND_CRITICAL_DISPATCH_ALERT", "session_id": session_id, "event_id": event_id, "task_id": third_id, "message": "12号观光车继续停运，等待三轮空载试车和复运审批。"}
    requested = await api.request("POST", "/api/v1/admin/action-requests", body=body, extra_headers={"Idempotency-Key": f"{run.run_id.lower()}-e2e-07"})
    approval_id = str(requested.get("approval_id") or "")
    approval = await api.request("GET", f"/api/v1/admin/approvals/{approval_id}")
    outbox_after = await api.request("GET", f"/api/v1/channels/simulator/sessions/{session_id}/outbox", params={"user_id": reporter_id})
    assertions = [
        _assertion("高风险调度告警创建待审批单", requested.get("status") == "pending_approval" and approval.get("status") == "PENDING" and approval.get("event_id") == event_id and approval.get("task_id") == third_id, {"request_status": requested.get("status"), "approval_status": approval.get("status"), "approval_id": approval_id}),
        _assertion("审批前动作未执行且接入环境未送达", approval.get("execution_status") in {None, "NOT_EXECUTED", "NOT_STARTED"} and not any(isinstance(item, dict) and item.get("approval_id") == approval_id and item.get("push_id") for item in _list_field(outbox_after, "items")), {"execution_status": approval.get("execution_status"), "outbox_before": len(_list_field(outbox_before, "items")), "outbox_after": len(_list_field(outbox_after, "items"))}),
        _assertion("审批保存场景证据快照", bool(_dict_field(approval, "evidence_snapshot")) and approval.get("tool_name") == "send_in_app_alert", {"tool_name": approval.get("tool_name"), "snapshot_present": bool(_dict_field(approval, "evidence_snapshot"))}),
    ]
    evidence = {
        "business_ids": {"venue_id": str(admin.get("venue_id") or ""), "event_id": event_id, "session_id": session_id, "task_id": third_id, "approval_id": approval_id or "missing-approval"},
        "references": ["POST /api/v1/admin/action-requests", f"GET /api/v1/admin/approvals/{approval_id}", f"GET /api/v1/channels/simulator/sessions/{session_id}/outbox"],
        "assertions": assertions, "model_calls": [],
        "artifacts": {"approval-request": requested, "approval": approval, "outbox-before": outbox_before, "outbox-after": outbox_after},
    }
    return _record_step_result(run, "E2E-07", passed=all(item["passed"] for item in assertions), evidence=evidence)


async def _run_e2e_08(api: _FormalClient, run: EvidenceRun, config: UATJourneyConfig) -> Path:
    if len(config.employee_password) < 12:
        raise UATJourneyError("E2E-08 要求 UAT_EMPLOYEE_PASSWORD 至少 12 位")
    admin = await api.login(config.admin_username, config.admin_password)
    prior = json.loads((run.path / "steps" / "E2E-07.json").read_text(encoding="utf-8"))
    prior_ids = _dict_field(prior, "business_ids")
    approval_id = str(prior_ids.get("approval_id") or "")
    event_id = str(prior_ids.get("event_id") or "")
    session_id = str(prior_ids.get("session_id") or "")
    task_id = str(prior_ids.get("task_id") or "")
    employee_id = str(_dict_field(json.loads((run.path / "steps" / "E2E-06.json").read_text(encoding="utf-8")), "business_ids").get("employee_user_id") or "")
    rejection = await api.request("POST", f"/api/v1/admin/approvals/{approval_id}/reject", body={"comment": "缺少三轮空载试车记录，请补证后重新提交。"})
    rejected = await api.request("GET", f"/api/v1/admin/approvals/{approval_id}")
    await api.request("PATCH", f"/api/v1/admin/tasks/{task_id}/assignment", body={"assigned_user_id": employee_id})
    employee_api = _FormalClient(api._client)
    await employee_api.login("li-ming", config.employee_password)
    started = _dict_field(await employee_api.request("POST", f"/api/v1/admin/tasks/{task_id}/start"), "task")
    result = {"summary": "完成三轮空载低速试车，异响消除且制动正常", "trials": [{"round": number, "noise": False, "brake_ok": True, "temperature_c": 30 + number} for number in range(1, 4)]}
    completed = _dict_field(await employee_api.request("POST", f"/api/v1/admin/tasks/{task_id}/complete", body={"result": result}), "task")
    body = {"action_code": "SEND_CRITICAL_DISPATCH_ALERT", "session_id": session_id, "event_id": event_id, "task_id": task_id, "supersedes_approval_id": approval_id, "message": "三轮空载试车正常，12号观光车继续停运，等待值班经理复运审批。"}
    resubmitted = await api.request("POST", "/api/v1/admin/action-requests", body=body, extra_headers={"Idempotency-Key": f"{run.run_id.lower()}-e2e-08"})
    revised_id = str(resubmitted.get("approval_id") or "")
    revised = await api.request("GET", f"/api/v1/admin/approvals/{revised_id}")
    snapshot = _dict_field(revised, "evidence_snapshot")
    assertions = [
        _assertion("第一张审批明确拒绝且动作未执行", rejection.get("rejected") is True and rejected.get("status") == "REJECTED" and rejected.get("execution_status") == "NOT_EXECUTED" and bool(rejected.get("comment")), {"status": rejected.get("status"), "execution_status": rejected.get("execution_status"), "comment": rejected.get("comment")}),
        _assertion("李明补齐三轮结构化试车证据", started.get("status") == "RUNNING" and completed.get("status") == "DONE" and len(_dict_field(completed, "result").get("trials", [])) == 3, {"task_status": completed.get("status"), "trials": _dict_field(completed, "result").get("trials")}),
        _assertion("新审批关联旧拒绝并冻结已完成任务证据", revised_id != approval_id and revised.get("status") == "PENDING" and revised.get("supersedes_approval_id") == approval_id and _dict_field(snapshot, "task").get("status") == "DONE", {"revised_id": revised_id, "supersedes": revised.get("supersedes_approval_id"), "snapshot_task_status": _dict_field(snapshot, "task").get("status")}),
    ]
    evidence = {"business_ids": {"venue_id": str(admin.get("venue_id") or ""), "event_id": event_id, "task_id": task_id, "rejected_approval_id": approval_id, "revised_approval_id": revised_id or "missing-revised-approval"}, "references": [f"POST /api/v1/admin/approvals/{approval_id}/reject", f"POST /api/v1/admin/tasks/{task_id}/complete", "POST /api/v1/admin/action-requests", f"GET /api/v1/admin/approvals/{revised_id}"], "assertions": assertions, "model_calls": [], "artifacts": {"rejected-approval": rejected, "trial-task": completed, "revised-approval": revised}}
    return _record_step_result(run, "E2E-08", passed=all(item["passed"] for item in assertions), evidence=evidence)


async def _run_e2e_09(api: _FormalClient, run: EvidenceRun, config: UATJourneyConfig) -> Path:
    admin = await api.login(config.admin_username, config.admin_password)
    prior = json.loads((run.path / "steps" / "E2E-08.json").read_text(encoding="utf-8"))
    prior_ids = _dict_field(prior, "business_ids")
    approval_id = str(prior_ids.get("revised_approval_id") or "")
    origin = json.loads((run.path / "steps" / "E2E-04.json").read_text(encoding="utf-8"))
    session_id = str(_dict_field(origin, "business_ids").get("session_id") or "")
    reporter = json.loads((run.path / "steps" / "E2E-01.json").read_text(encoding="utf-8"))
    reporter_id = str(_dict_field(reporter, "business_ids").get("user_id") or "")
    approved = await api.request("POST", f"/api/v1/admin/approvals/{approval_id}/approve", body={"comment": "三轮试车证据齐全，同意发送调度告警。"})
    approval = await api.request("GET", f"/api/v1/admin/approvals/{approval_id}")
    outbox = await api.request("GET", f"/api/v1/channels/simulator/sessions/{session_id}/outbox", params={"user_id": reporter_id})
    delivered = [item for item in _list_field(outbox, "items") if isinstance(item, dict) and item.get("approval_id") == approval_id and item.get("push_id") and item.get("delivery_status") == "DELIVERED"]
    assertions = [
        _assertion("值班经理批准后受控动作执行成功", approved.get("approved") is True and approval.get("status") == "APPROVED" and approval.get("execution_status") == "SUCCEEDED", {"status": approval.get("status"), "execution_status": approval.get("execution_status")}),
        _assertion("本次审批只生成一条已送达通知", len(delivered) == 1, {"delivered_count": len(delivered), "push_ids": [item.get("push_id") for item in delivered]}),
        _assertion("被拒绝的审批仍保持未执行", any(isinstance(item, dict) and item.get("approval_id") == prior_ids.get("rejected_approval_id") and item.get("status") == "REJECTED" and not item.get("push_id") for item in _list_field(outbox, "items")), {"outbox_count": len(_list_field(outbox, "items"))}),
    ]
    evidence = {"business_ids": {"venue_id": str(admin.get("venue_id") or ""), "event_id": str(prior_ids.get("event_id") or ""), "approval_id": approval_id, "push_id": str(delivered[0].get("push_id") if delivered else "missing-push")}, "references": [f"POST /api/v1/admin/approvals/{approval_id}/approve", f"GET /api/v1/admin/approvals/{approval_id}", f"GET /api/v1/channels/simulator/sessions/{session_id}/outbox"], "assertions": assertions, "model_calls": [], "artifacts": {"approved": approved, "approval": approval, "outbox": outbox}}
    return _record_step_result(run, "E2E-09", passed=all(item["passed"] for item in assertions), evidence=evidence)


async def _run_e2e_10(api: _FormalClient, run: EvidenceRun, config: UATJourneyConfig) -> Path:
    if len(config.employee_password) < 12:
        raise UATJourneyError("E2E-10 要求 UAT_EMPLOYEE_PASSWORD 至少 12 位")
    admin = await api.login(config.admin_username, config.admin_password)
    prior = json.loads((run.path / "steps" / "E2E-09.json").read_text(encoding="utf-8"))
    event_id = str(_dict_field(prior, "business_ids").get("event_id") or "")
    task_id = str(_e2e_05_tasks(run)[3]["id"])
    resolution = "车辆已停运隔离，检修右后轮并完成三轮空载试车，调度告警已审批送达，后续观察轮端温度。"
    blocked_close = await api.expect_rejection("POST", f"/api/v1/admin/events/{event_id}/close", body={"resolution": resolution}, expected_statuses=(409,))
    before = _dict_field(await api.request("GET", f"/api/v1/admin/tasks/{task_id}"), "task")
    users = _list_field(await api.request("GET", "/api/v1/admin/users"), "users")
    manager = next((user for user in users if isinstance(user, dict) and user.get("username") == "wang-fang"), {})
    manager_id = str(manager.get("id") or "")
    if not manager_id:
        raise UATJourneyError("E2E-10 未找到王芳的正式身份")
    assigned = _dict_field(await api.request("PATCH", f"/api/v1/admin/tasks/{task_id}/assignment", body={"assigned_user_id": manager_id}), "task")
    manager_api = _FormalClient(api._client)
    manager_principal = await manager_api.login("wang-fang", config.employee_password)
    started = _dict_field(await manager_api.request("POST", f"/api/v1/admin/tasks/{task_id}/start"), "task")
    completed = _dict_field(await manager_api.request("POST", f"/api/v1/admin/tasks/{task_id}/complete", body={"result": {"summary": "三轮试车证据、调度审批与送达记录已核对，保持停运观察后进入闭环检查", "approval_id": str(_dict_field(prior, "business_ids").get("approval_id") or ""), "evidence_complete": True}}), "task")
    after = _dict_field(await api.request("GET", f"/api/v1/admin/tasks/{task_id}"), "task")
    assertions = [
        _assertion("末项任务未完成时服务端拒绝关闭事件", blocked_close.get("status_code") == 409 and _dict_field(blocked_close, "detail").get("code") == "EVENT_CLOSE_BLOCKED" and before.get("status") != "DONE", {"rejection": blocked_close, "task_status": before.get("status")}),
        _assertion("值班经理以独立身份执行末项任务", manager_principal.get("role") == "manager" and manager_principal.get("id") == manager_id and assigned.get("assigned_user_id") == manager_id and started.get("status") == "RUNNING", {"manager_id": manager_id, "started": started.get("status")}),
        _assertion("末项任务提交审批关联结果并持久化", completed.get("status") == "DONE" and after.get("status") == "DONE" and _dict_field(after, "result").get("approval_id") == _dict_field(prior, "business_ids").get("approval_id"), {"status": after.get("status"), "result": after.get("result")}),
    ]
    evidence = {"business_ids": {"venue_id": str(admin.get("venue_id") or ""), "event_id": event_id, "task_id": task_id, "manager_user_id": manager_id}, "references": [f"POST /api/v1/admin/events/{event_id}/close", f"PATCH /api/v1/admin/tasks/{task_id}/assignment", f"POST /api/v1/admin/tasks/{task_id}/complete", f"GET /api/v1/admin/tasks/{task_id}"], "assertions": assertions, "model_calls": [], "artifacts": {"close-rejection": blocked_close, "task-before": before, "task-completed": completed, "task-after": after}}
    return _record_step_result(run, "E2E-10", passed=all(item["passed"] for item in assertions), evidence=evidence)


async def _run_e2e_11(api: _FormalClient, run: EvidenceRun, config: UATJourneyConfig) -> Path:
    admin = await api.login(config.admin_username, config.admin_password)
    prior = json.loads((run.path / "steps" / "E2E-10.json").read_text(encoding="utf-8"))
    event_id = str(_dict_field(prior, "business_ids").get("event_id") or "")
    check = await api.request("POST", f"/api/v1/admin/events/{event_id}/watcher-check")
    watcher_run = _dict_field(check, "run")
    trace_id = str(check.get("trace_id") or "")
    llm_payload = await api.request("GET", "/api/v1/admin/llm-calls", params={"trace_id": trace_id})
    calls = [item for item in _list_field(llm_payload, "llm_calls") if isinstance(item, dict) and item.get("agent_id") == "Watcher" and item.get("trace_id") == trace_id and item.get("provider") == "deepseek" and item.get("model_name") == "deepseek-flash" and item.get("is_mock") is False and item.get("status") == "SUCCEEDED"]
    model_calls = [{"agent": "Watcher", "provider": item.get("provider"), "model": item.get("model_name"), "is_mock": item.get("is_mock"), "request_id": item.get("request_id"), "trace_id": trace_id, "status": item.get("status")} for item in calls]
    assertions = [
        _assertion("Watcher 使用真实 DeepSeek 对本事件运行", bool(model_calls) and watcher_run.get("event_id") == event_id and watcher_run.get("status") == "SUCCEEDED", {"run_id": watcher_run.get("id"), "run_status": watcher_run.get("status"), "call_count": len(model_calls)}),
        _assertion("目标快照包含事件与任务处置证据", watcher_run.get("target_count") == 1 and bool(watcher_run.get("target_snapshot")), {"target_count": watcher_run.get("target_count"), "snapshot_present": bool(watcher_run.get("target_snapshot"))}),
        _assertion("本次闭环检查无 finding", check.get("ready_to_close") is True and not _list_field(check, "findings") and watcher_run.get("finding_count") == 0, {"ready_to_close": check.get("ready_to_close"), "finding_count": watcher_run.get("finding_count")}),
    ]
    evidence = {"business_ids": {"venue_id": str(admin.get("venue_id") or ""), "event_id": event_id, "watcher_run_id": str(watcher_run.get("id") or "missing-run"), "trace_id": trace_id or "missing-trace"}, "references": [f"POST /api/v1/admin/events/{event_id}/watcher-check", "GET /api/v1/admin/llm-calls"], "assertions": assertions, "model_calls": model_calls, "artifacts": {"watcher-check": check, "model-call-metadata": {"calls": model_calls}}}
    return _record_step_result(run, "E2E-11", passed=all(item["passed"] for item in assertions), evidence=evidence)


async def _run_e2e_12(api: _FormalClient, run: EvidenceRun, config: UATJourneyConfig) -> Path:
    admin = await api.login(config.admin_username, config.admin_password)
    prior = json.loads((run.path / "steps" / "E2E-11.json").read_text(encoding="utf-8"))
    event_id = str(_dict_field(prior, "business_ids").get("event_id") or "")
    resolution = "车辆已停运隔离，右后轮检修后完成三轮空载试车且制动正常，调度告警经审批送达，后续持续观察轮端温度。"
    closed = await api.request("POST", f"/api/v1/admin/events/{event_id}/close", body={"resolution": resolution})
    event = await api.request("GET", f"/api/v1/admin/events/{event_id}")
    candidate_result = _dict_field(closed, "experience_candidate")
    retries: list[dict[str, Any]] = []
    if candidate_result.get("outcome") not in {"CREATED", "REPLAYED"} and candidate_result.get("retryable") is True:
        for _attempt in range(2):
            candidate_result = await api.request("POST", f"/api/v1/admin/events/{event_id}/experience-candidate/retry")
            retries.append(candidate_result)
            if candidate_result.get("outcome") in {"CREATED", "REPLAYED"}:
                break
    candidate = _dict_field(candidate_result, "candidate")
    extraction = _dict_field(candidate_result, "extraction")
    trace_id = str(extraction.get("trace_id") or closed.get("trace_id") or "")
    llm_payload = await api.request("GET", "/api/v1/admin/llm-calls", params={"trace_id": trace_id})
    calls = [item for item in _list_field(llm_payload, "llm_calls") if isinstance(item, dict) and item.get("agent_id") == "PersonaExtract" and item.get("trace_id") == trace_id and item.get("provider") == "deepseek" and item.get("model_name") == "deepseek-flash" and item.get("is_mock") is False and item.get("status") == "SUCCEEDED"]
    model_calls = [{"agent": "PersonaExtract", "provider": item.get("provider"), "model": item.get("model_name"), "is_mock": item.get("is_mock"), "request_id": item.get("request_id"), "trace_id": trace_id, "status": item.get("status")} for item in calls]
    assertions = [
        _assertion("事件在闭环门禁通过后成功关闭", closed.get("closed") is True and _dict_field(closed, "closure_conditions").get("ready") is True and event.get("status") == "CLOSED", {"closed": closed.get("closed"), "status": event.get("status")}),
        _assertion("PersonaExtract 真实模型生成本事件草稿候选", bool(model_calls) and candidate_result.get("outcome") in {"CREATED", "REPLAYED"} and candidate.get("source_event_id") == event_id and extraction.get("status") == "SUCCEEDED", {"outcome": candidate_result.get("outcome"), "candidate_id": candidate.get("id"), "extraction_status": extraction.get("status"), "call_count": len(model_calls)}),
        _assertion("候选尚未发布或建立检索索引", candidate.get("status") == "DRAFT" and candidate.get("index_status") == "NOT_INDEXED" and bool(candidate.get("id")), {"status": candidate.get("status"), "index_status": candidate.get("index_status")}),
    ]
    evidence = {"business_ids": {"venue_id": str(admin.get("venue_id") or ""), "event_id": event_id, "candidate_id": str(candidate.get("id") or "missing-candidate"), "trace_id": trace_id or "missing-trace"}, "references": [f"POST /api/v1/admin/events/{event_id}/close", f"GET /api/v1/admin/events/{event_id}", f"POST /api/v1/admin/events/{event_id}/experience-candidate/retry", "GET /api/v1/admin/llm-calls"], "assertions": assertions, "model_calls": model_calls, "artifacts": {"close-result": closed, "event-after": event, "candidate-result": candidate_result, "candidate-retries": {"attempts": retries}, "model-call-metadata": {"calls": model_calls}}}
    return _record_step_result(run, "E2E-12", passed=all(item["passed"] for item in assertions), evidence=evidence)


async def _run_e2e_13(api: _FormalClient, run: EvidenceRun, config: UATJourneyConfig) -> Path:
    if len(config.employee_password) < 12:
        raise UATJourneyError("E2E-13 要求 UAT_EMPLOYEE_PASSWORD 至少 12 位")
    admin = await api.login(config.admin_username, config.admin_password)
    prior = json.loads((run.path / "steps" / "E2E-12.json").read_text(encoding="utf-8"))
    event_id = str(_dict_field(prior, "business_ids").get("event_id") or "")
    experts = _list_field(await api.request("GET", "/api/v1/admin/experts"), "experts")
    expert = next((item for item in experts if isinstance(item, dict) and item.get("display_name") == "张建国" and item.get("authorization_status") == "SIGNED"), {})
    expert_id = str(expert.get("id") or "")
    if not expert_id:
        raise UATJourneyError("E2E-13 缺少已签署授权的张建国专家档案")
    invited = _dict_field(await api.request("POST", "/api/v1/admin/experience-interviews", body={"expert_id": expert_id, "title": "12号观光车雨后轮端异响处置经验", "source_event_id": event_id, "authorization_scopes": [{"scope_type": "VENUE", "scope_value": "venue-yueshan"}]}), "interview")
    interview_id = str(invited.get("id") or "")
    expert_api = _FormalClient(api._client)
    expert_principal = await expert_api.login("zhang-jianguo", config.employee_password)
    accepted = _dict_field(await expert_api.request("POST", f"/api/v1/assistant/experience/interviews/{interview_id}/accept"), "interview")
    answers = (
        "雨后轮端金属摩擦声、水迹和温升要分别检查，防尘护板与制动盘间隙低于2毫米是停运信号。",
        "先停运断电封钥，检查右后轮护板和制动盘间隙，修复后做三轮空载低速试车并逐轮记录温度与异响。",
        "只要仍有持续摩擦、制动跑偏、裂纹或温度异常，立即停止试车并升级设备主管，不能载客。",
        "适用于悦山景区雨后涉水的观光车轮端异常；没有检修与三轮试车证据不得复运，其他车型需另行评估。",
    )
    turns: list[dict[str, Any]] = []
    first_key = f"{run.run_id.lower()}-interview-1"
    first = await expert_api.request("POST", f"/api/v1/assistant/experience/interviews/{interview_id}/answers", body={"answer": answers[0]}, extra_headers={"Idempotency-Key": first_key})
    turns.append(_dict_field(first, "turn"))
    replay = await expert_api.request("POST", f"/api/v1/assistant/experience/interviews/{interview_id}/answers", body={"answer": answers[0]}, extra_headers={"Idempotency-Key": first_key})
    paused = _dict_field(await expert_api.request("POST", f"/api/v1/assistant/experience/interviews/{interview_id}/pause"), "interview")
    restored = _dict_field(await expert_api.request("GET", f"/api/v1/assistant/experience/interviews/{interview_id}"), "interview")
    resumed = _dict_field(await expert_api.request("POST", f"/api/v1/assistant/experience/interviews/{interview_id}/resume"), "interview")
    for number, answer in enumerate(answers[1:], start=2):
        response = await expert_api.request("POST", f"/api/v1/assistant/experience/interviews/{interview_id}/answers", body={"answer": answer}, extra_headers={"Idempotency-Key": f"{run.run_id.lower()}-interview-{number}"})
        turns.append(_dict_field(response, "turn"))
    completed = await expert_api.request("POST", f"/api/v1/assistant/experience/interviews/{interview_id}/complete")
    card = _dict_field(completed, "card")
    card_id = str(card.get("id") or "")
    confirmed = _dict_field(await expert_api.request("POST", f"/api/v1/assistant/experience/cards/{card_id}/confirm"), "card")
    interview = _dict_field(await api.request("GET", f"/api/v1/admin/experience-interviews/{interview_id}"), "interview")
    trace_id = str(completed.get("trace_id") or "")
    llm_payload = await api.request("GET", "/api/v1/admin/llm-calls", params={"trace_id": trace_id})
    calls = [item for item in _list_field(llm_payload, "llm_calls") if isinstance(item, dict) and item.get("agent_id") == "PersonaExtract" and item.get("trace_id") == trace_id and item.get("provider") == "deepseek" and item.get("model_name") == "deepseek-flash" and item.get("is_mock") is False and item.get("status") == "SUCCEEDED"]
    model_calls = [{"agent": "PersonaExtract", "provider": item.get("provider"), "model": item.get("model_name"), "is_mock": item.get("is_mock"), "request_id": item.get("request_id"), "trace_id": trace_id, "status": item.get("status")} for item in calls]
    assertions = [
        _assertion("已授权专家以独立身份接受本事件访谈", expert_principal.get("id") == expert.get("user_id") and invited.get("source_event_id") == event_id and accepted.get("status") == "ACCEPTED", {"expert_id": expert_id, "interview_id": interview_id, "source_event_id": invited.get("source_event_id")}),
        _assertion("四轮回答去重且暂停刷新后可恢复", len(turns) == 4 and [item.get("turn_number") for item in turns] == [1, 2, 3, 4] and replay.get("idempotent_replay") is True and paused.get("status") == "PAUSED" and restored.get("progress", {}).get("answered") == 1 and resumed.get("status") == "IN_PROGRESS" and len(_list_field(interview, "turns")) == 4, {"turn_numbers": [item.get("turn_number") for item in turns], "replay": replay.get("idempotent_replay"), "restored_progress": restored.get("progress")}),
        _assertion("PersonaExtract 真实调用生成并由专家确认经验卡", bool(model_calls) and interview.get("status") == "COMPLETED" and confirmed.get("status") == "EXPERT_CONFIRMED" and confirmed.get("source_event_id") == event_id and confirmed.get("current_version") == 1, {"card_id": card_id, "status": confirmed.get("status"), "model_calls": len(model_calls)}),
    ]
    evidence = {"business_ids": {"venue_id": str(admin.get("venue_id") or ""), "event_id": event_id, "expert_id": expert_id, "interview_id": interview_id, "experience_card_id": card_id or "missing-card", "trace_id": trace_id or "missing-trace"}, "references": ["POST /api/v1/admin/experience-interviews", f"POST /api/v1/assistant/experience/interviews/{interview_id}/accept", f"POST /api/v1/assistant/experience/interviews/{interview_id}/answers", f"POST /api/v1/assistant/experience/interviews/{interview_id}/complete", f"POST /api/v1/assistant/experience/cards/{card_id}/confirm"], "assertions": assertions, "model_calls": model_calls, "artifacts": {"interview": interview, "turns": {"turns": turns}, "replay": replay, "paused": paused, "restored": restored, "resumed": resumed, "card-confirmed": confirmed}}
    return _record_step_result(run, "E2E-13", passed=all(item["passed"] for item in assertions), evidence=evidence)


async def _run_e2e_14(api: _FormalClient, run: EvidenceRun, config: UATJourneyConfig) -> Path:
    admin = await api.login(config.admin_username, config.admin_password)
    prior = json.loads((run.path / "steps" / "E2E-13.json").read_text(encoding="utf-8"))
    prior_ids = _dict_field(prior, "business_ids")
    card_id = str(prior_ids.get("experience_card_id") or "")
    before = _dict_field(await api.request("GET", f"/api/v1/admin/experience-cards/{card_id}"), "experience_card")
    submitted = _dict_field(await api.request("POST", f"/api/v1/admin/experience-cards/{card_id}/submit"), "card")
    rejected = _dict_field(await api.request("POST", f"/api/v1/admin/experience-cards/{card_id}/reject", body={"comment": "请明确2毫米检查阈值和复运前禁载客要求。"}), "card")
    expert_api = _FormalClient(api._client)
    await expert_api.login("zhang-jianguo", config.employee_password)
    decision_rule = str(before.get("decision_rule") or "").rstrip("。") + "；防尘护板间隙低于2毫米或持续摩擦时禁止载客，三轮空载试车和经理审批齐全后才可复运。"
    revised = _dict_field(await expert_api.request("PUT", f"/api/v1/assistant/experience/cards/{card_id}", body={"decision_rule": decision_rule, "change_note": "补充2毫米阈值与复运前禁载客限制"}), "card")
    confirmed = _dict_field(await expert_api.request("POST", f"/api/v1/assistant/experience/cards/{card_id}/confirm"), "card")
    resubmitted = _dict_field(await api.request("POST", f"/api/v1/admin/experience-cards/{card_id}/submit"), "card")
    published = _dict_field(await api.request("POST", f"/api/v1/admin/experience-cards/{card_id}/publish", body={"comment": "复审通过，发布至悦山景区内部。"}), "card")
    detail = _dict_field(await api.request("GET", f"/api/v1/admin/experience-cards/{card_id}"), "experience_card")
    versions = _list_field(detail, "versions")
    initial_version = next((item for item in versions if isinstance(item, dict) and item.get("version_number") == 1), {})
    actions = [item.get("action") for item in _list_field(detail, "review_timeline") if isinstance(item, dict)]
    assertions = [
        _assertion("审核退回并由专家修订后重新确认", submitted.get("status") == "IN_REVIEW" and rejected.get("status") == "DRAFT" and revised.get("current_version") == 2 and confirmed.get("status") == "EXPERT_CONFIRMED" and resubmitted.get("status") == "IN_REVIEW", {"submitted": submitted.get("status"), "rejected": rejected.get("status"), "revised_version": revised.get("current_version"), "resubmitted": resubmitted.get("status")}),
        _assertion("旧版本快照不可变且审核轨迹完整", len(versions) == 2 and _dict_field(initial_version, "snapshot").get("decision_rule") == before.get("decision_rule") and actions == ["CONFIRM", "SUBMIT", "REJECT", "REVISE", "CONFIRM", "SUBMIT", "PUBLISH"], {"versions": [item.get("version_number") for item in versions], "actions": actions}),
        _assertion("经验发布版本与 pgvector 索引一致", published.get("status") == "PUBLISHED" and detail.get("status") == "PUBLISHED" and detail.get("index_status") == "INDEXED" and detail.get("published_version") == 2 and detail.get("vector_doc_id") == f"experience:venue-yueshan:{card_id}:v2", {"status": detail.get("status"), "index_status": detail.get("index_status"), "published_version": detail.get("published_version"), "vector_doc_id": detail.get("vector_doc_id")}),
    ]
    evidence = {"business_ids": {"venue_id": str(admin.get("venue_id") or ""), "event_id": str(prior_ids.get("event_id") or ""), "experience_card_id": card_id, "published_version": str(detail.get("published_version") or "missing-version"), "vector_doc_id": str(detail.get("vector_doc_id") or "missing-index")}, "references": [f"POST /api/v1/admin/experience-cards/{card_id}/submit", f"POST /api/v1/admin/experience-cards/{card_id}/reject", f"PUT /api/v1/assistant/experience/cards/{card_id}", f"POST /api/v1/admin/experience-cards/{card_id}/publish", f"GET /api/v1/admin/experience-cards/{card_id}"], "assertions": assertions, "model_calls": [], "artifacts": {"card-before": before, "card-rejected": rejected, "card-revised": revised, "card-published": published, "card-detail": detail}}
    return _record_step_result(run, "E2E-14", passed=all(item["passed"] for item in assertions), evidence=evidence)


async def _run_uat_f01(api: _FormalClient, run: EvidenceRun, config: UATJourneyConfig) -> Path:
    admin = await api.login(config.admin_username, config.admin_password)
    first = json.loads((run.path / "steps" / "E2E-02.json").read_text(encoding="utf-8"))
    first_ids = _dict_field(first, "business_ids")
    decomposed = json.loads((run.path / "steps" / "E2E-05.json").read_text(encoding="utf-8"))
    decomposition_ids = _dict_field(decomposed, "business_ids")
    session_id = str(first_ids.get("session_id") or "")
    tasks_before = _list_field(await api.request("GET", "/api/v1/admin/tasks", params={"session_id": session_id}), "tasks")
    audit_before = _list_field(await api.request("GET", "/api/v1/admin/audit-logs", params={"trace_id": str(first_ids.get("trace_id") or "")}), "audit_logs")
    message = {"user_id": first_ids.get("user_id"), "content": "12号观光车刚做开园前试车，右后轮间歇性金属摩擦声，昨晚下过大雨，车上没人。我已经把车停在维修区并断电了，下一步怎么处理？", "external_message_id": first_ids.get("external_message_id"), "external_conversation_id": f"{run.run_id.lower()}-li-ming", "metadata": {"venue_id": "forged-venue-must-be-ignored", "uat_run_id": run.run_id}, "attachments": [{"attachment_id": first_ids.get("attachment_id"), "description": "右后轮内侧有水迹，车辆已断电，现场无人受伤"}]}
    replayed_message = await api.request("POST", "/api/v1/channels/simulator/messages", body=message)
    replayed_decomposition = await api.request("POST", "/api/v1/admin/tasks/decompose", body={"goal": _task_decomposition_goal(), "session_id": session_id, "event_id": decomposition_ids.get("event_id")}, extra_headers={"Idempotency-Key": str(decomposition_ids.get("idempotency_key") or "")})
    tasks_after = _list_field(await api.request("GET", "/api/v1/admin/tasks", params={"session_id": session_id}), "tasks")
    audit_after = _list_field(await api.request("GET", "/api/v1/admin/audit-logs", params={"trace_id": str(first_ids.get("trace_id") or "")}), "audit_logs")
    original_task_ids = {str(task.get("id")) for task in _e2e_05_tasks(run)}
    replay_task_ids = {str(task.get("id")) for task in _list_field(replayed_decomposition, "tasks") if isinstance(task, dict)}
    assertions = [
        _assertion("重复消息返回原消息、Trace 与会话", replayed_message.get("duplicate") is True and all(replayed_message.get(key) == first_ids.get(key) for key in ("message_id", "trace_id", "session_id")), {"duplicate": replayed_message.get("duplicate"), "message_id": replayed_message.get("message_id")}),
        _assertion("重复消息不再次产生入队审计", len(audit_after) == len(audit_before), {"audit_before": len(audit_before), "audit_after": len(audit_after)}),
        _assertion("TodoWrite 幂等重放保持原四任务图", replayed_decomposition.get("decomposition_id") == decomposition_ids.get("decomposition_id") and replay_task_ids == original_task_ids and len(tasks_after) == len(tasks_before), {"decomposition_id": replayed_decomposition.get("decomposition_id"), "task_count_before": len(tasks_before), "task_count_after": len(tasks_after)}),
    ]
    evidence = {"business_ids": {"venue_id": str(admin.get("venue_id") or ""), "session_id": session_id, "message_id": str(first_ids.get("message_id") or ""), "decomposition_id": str(decomposition_ids.get("decomposition_id") or "")}, "references": ["POST /api/v1/channels/simulator/messages", "POST /api/v1/admin/tasks/decompose", "GET /api/v1/admin/tasks", "GET /api/v1/admin/audit-logs"], "assertions": assertions, "model_calls": [], "artifacts": {"replayed-message": replayed_message, "replayed-decomposition": replayed_decomposition, "tasks-before": {"tasks": tasks_before}, "tasks-after": {"tasks": tasks_after}}}
    return _record_step_result(run, "UAT-F01", passed=all(item["passed"] for item in assertions), evidence=evidence)


async def _run_uat_f04(api: _FormalClient, run: EvidenceRun, config: UATJourneyConfig) -> Path:
    admin = await api.login(config.admin_username, config.admin_password)
    prior = json.loads((run.path / "steps" / "E2E-14.json").read_text(encoding="utf-8"))
    card_id = str(_dict_field(prior, "business_ids").get("experience_card_id") or "")
    employee_api = _FormalClient(api._client)
    await employee_api.login("zhou-qi", config.employee_password)
    body = {"query": "雨后观光车右后轮摩擦声，停运检修和复运审批", "top_k": 5, "threshold": 0.0}
    before = await employee_api.request("POST", "/api/v1/assistant/experience/search", body=body)
    docker = _IsolatedDocker()
    stopped = await docker.stop()
    try:
        failure = await employee_api.expect_rejection("POST", "/api/v1/assistant/experience/search", body=body, expected_statuses=(503,))
    finally:
        restored = await docker.start()
    after = await employee_api.request("POST", "/api/v1/assistant/experience/search", body=body)
    before_hit = next((item for item in _list_field(before, "experiences") if isinstance(item, dict) and item.get("id") == card_id), {})
    after_hit = next((item for item in _list_field(after, "experiences") if isinstance(item, dict) and item.get("id") == card_id), {})
    assertions = [
        _assertion("故障前真实 pgvector 检索命中已发布经验", bool(before_hit) and before_hit.get("published") is True, {"card_id": card_id, "hit_count": len(_list_field(before, "experiences"))}),
        _assertion("TEI 停止时经验检索明确返回可重试失败", stopped["stopped"].get("running") is False and failure.get("status_code") == 503 and _dict_field(failure, "detail").get("code") == "EXPERIENCE_SEARCH_FAILED", failure),
        _assertion("TEI 恢复健康后同一经验再次检索成功", restored.get("health") == "healthy" and bool(after_hit) and after_hit.get("version") == before_hit.get("version"), {"health": restored.get("health"), "card_id": after_hit.get("id"), "version": after_hit.get("version")}),
    ]
    evidence = {"business_ids": {"venue_id": str(admin.get("venue_id") or ""), "experience_card_id": card_id, "tei_container_id": str(restored.get("container_id") or "")}, "references": ["POST /api/v1/assistant/experience/search", "Docker Engine /containers/tei-embedding/stop", "Docker Engine /containers/tei-embedding/start"], "assertions": assertions, "model_calls": [], "artifacts": {"search-before": before, "tei-stopped": stopped, "search-failure": failure, "tei-restored": restored, "search-after": after}}
    return _record_step_result(run, "UAT-F04", passed=all(item["passed"] for item in assertions), evidence=evidence)


async def _run_uat_f02(api: _FormalClient, run: EvidenceRun, config: UATJourneyConfig) -> Path:
    admin = await api.login(config.admin_username, config.admin_password)
    prior = json.loads((run.path / "steps" / "UAT-F09.json").read_text(encoding="utf-8"))
    prior_ids = _dict_field(prior, "business_ids")
    message = json.loads((run.path / "artifacts" / "UAT-F09" / "message.json").read_text(encoding="utf-8"))
    trace_id = str(prior_ids.get("trace_id") or "")
    session_id = str(message.get("session_id") or "")
    message_id = str(message.get("message_id") or "")
    events_before = _list_field(await api.request("GET", "/api/v1/admin/events"), "events")
    matching_before = [item for item in events_before if isinstance(item, dict) and item.get("trace_id") == trace_id]
    tasks_before = _list_field(await api.request("GET", "/api/v1/admin/tasks", params={"session_id": session_id}), "tasks")
    docker = _IsolatedDocker("app")
    redis_client = redis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379/0"))
    stream = "memory_palace:messages"
    group = "mp_workers"
    injected_id = ""
    pending_before = 0
    try:
        queue_before = await redis_client.xpending(stream, group)
        group_info = await redis_client.xinfo_groups(stream)
        lag_before = next((int(item.get("lag") or 0) for item in group_info if item.get("name") in {group, group.encode()}), -1)
        if queue_before.get("pending") != 0 or lag_before != 0:
            raise UATJourneyError("UAT-F02 要求隔离队列无既有 pending 或 lag")
        original_data = None
        for _entry_id, fields in await redis_client.xrevrange(stream, count=200):
            raw_data = fields.get(b"data")
            if raw_data and json.loads(raw_data).get("msg_id") == message_id:
                original_data = raw_data
                break
        if original_data is None:
            raise UATJourneyError("UAT-F02 找不到本次正式消息的 Redis 原始载荷")
        stopped = await docker.stop()
        try:
            injected_id = (await redis_client.xadd(stream, {"data": original_data})).decode()
            claimed = await redis_client.xreadgroup(group, "uat_before_restart", {stream: ">"}, count=1)
            claimed_ids = [entry_id.decode() for _stream, entries in claimed for entry_id, _fields in entries]
            pending_before = int((await redis_client.xpending(stream, group)).get("pending") or 0)
        finally:
            restored = await docker.start()
        pending_after = 1
        recovery: dict[str, Any] = {}
        for _attempt in range(50):
            pending_after = int((await redis_client.xpending(stream, group)).get("pending") or 0)
            recovery_runs = _list_field(await api.request("GET", "/api/v1/admin/recovery-runs"), "recovery_runs")
            recovery = next((item for item in recovery_runs if isinstance(item, dict) and item.get("instance_id") == restored.get("container_id")), {})
            if not recovery:
                diagnostics = await api.request("GET", "/api/v1/admin/diagnostics")
                instance_id = str(_dict_field(_dict_field(diagnostics, "runtime"), "app").get("instance_id") or "")
                recovery = next((item for item in recovery_runs if isinstance(item, dict) and item.get("instance_id") == instance_id), {})
            if pending_after == 0 and int(recovery.get("redis_acked_count") or 0) >= 1:
                break
            await asyncio.sleep(2)
    finally:
        await redis_client.aclose()
    events_after = _list_field(await api.request("GET", "/api/v1/admin/events"), "events")
    matching_after = [item for item in events_after if isinstance(item, dict) and item.get("trace_id") == trace_id]
    tasks_after = _list_field(await api.request("GET", "/api/v1/admin/tasks", params={"session_id": session_id}), "tasks")
    assertions = [
        _assertion("Worker 停止后同一正式消息进入 Redis pending 且未 ACK", stopped["stopped"].get("running") is False and claimed_ids == [injected_id] and pending_before == 1, {"stream_message_id": injected_id, "claimed_ids": claimed_ids, "pending_before": pending_before}),
        _assertion("Worker 启动回收 pending 并完成 ACK", restored.get("health") == "healthy" and pending_after == 0 and int(recovery.get("redis_pending_count") or 0) >= 1 and int(recovery.get("redis_claimed_count") or 0) >= 1 and int(recovery.get("redis_acked_count") or 0) >= 1, {"pending_after": pending_after, "recovery_id": recovery.get("id"), "pending_count": recovery.get("redis_pending_count"), "claimed_count": recovery.get("redis_claimed_count"), "acked_count": recovery.get("redis_acked_count")}),
        _assertion("重放原消息未复制事件或任务", len(matching_before) == len(matching_after) == 1 and {item.get("id") for item in tasks_before if isinstance(item, dict)} == {item.get("id") for item in tasks_after if isinstance(item, dict)}, {"events_before": len(matching_before), "events_after": len(matching_after), "tasks_before": len(tasks_before), "tasks_after": len(tasks_after)}),
    ]
    evidence = {"business_ids": {"venue_id": str(admin.get("venue_id") or ""), "event_id": str(prior_ids.get("event_id") or ""), "session_id": session_id, "trace_id": trace_id, "stream_message_id": injected_id, "recovery_id": str(recovery.get("id") or "")}, "references": ["Redis Streams XADD/XREADGROUP/XPENDING", "Docker Engine /containers/app/stop", "Docker Engine /containers/app/start", "GET /api/v1/admin/recovery-runs", "GET /api/v1/admin/events", "GET /api/v1/admin/tasks"], "assertions": assertions, "model_calls": [], "artifacts": {"queue-before": {"pending": queue_before.get("pending"), "lag": lag_before}, "app-stopped": stopped, "pending-injected": {"stream_message_id": injected_id, "claimed_ids": claimed_ids, "pending": pending_before}, "app-restored": restored, "recovery": recovery, "queue-after": {"pending": pending_after}, "business-counts": {"events_before": len(matching_before), "events_after": len(matching_after), "tasks_before": len(tasks_before), "tasks_after": len(tasks_after)}}}
    return _record_step_result(run, "UAT-F02", passed=all(item["passed"] for item in assertions), evidence=evidence)


async def probe_uat_f03(config: UATJourneyConfig, run: EvidenceRun, mode: str) -> Path:
    if mode not in {"unauthorized-1", "unauthorized-2", "timeout"}:
        raise UATJourneyError("不支持的 DeepSeek 故障探针")
    if "UAT-F09" not in _passed_step_ids(run):
        raise UATJourneyError("UAT-F03 探针要求同一证据包中的 UAT-F09 已通过")
    snapshot_path = run.path / "api" / f"f03-{mode}.json"
    if snapshot_path.exists():
        raise FileExistsError("同一 DeepSeek 故障探针已有不可变快照")
    message = json.loads((run.path / "artifacts" / "UAT-F09" / "message.json").read_text(encoding="utf-8"))
    session_id = str(message.get("session_id") or "")
    async with httpx.AsyncClient(base_url=config.base_url, timeout=max(config.timeout_seconds, 60), trust_env=False) as client:
        api = _FormalClient(client)
        await api.login(config.admin_username, config.admin_password)
        tasks_before = _list_field(await api.request("GET", "/api/v1/admin/tasks", params={"session_id": session_id}), "tasks")
        headers = {"Authorization": f"Bearer {api._access_token}", "Idempotency-Key": f"{run.run_id.lower()}-f03-{mode}"}
        response = await client.post("/api/v1/admin/tasks/decompose", json={"goal": _task_decomposition_goal(), "session_id": session_id}, headers=headers)
        if response.status_code != 502:
            raise UATJourneyError(f"DeepSeek 故障未被正式任务接口安全拒绝：{mode} -> {response.status_code}")
        failure = response.json()
        detail = _dict_field(failure, "detail")
        trace_id = str(detail.get("trace_id") or "")
        calls = _list_field(await api.request("GET", "/api/v1/admin/llm-calls", params={"trace_id": trace_id}), "llm_calls")
        tasks_after = _list_field(await api.request("GET", "/api/v1/admin/tasks", params={"session_id": session_id}), "tasks")
        diagnostics = await api.request("GET", "/api/v1/admin/diagnostics")
    payload = {"mode": mode, "session_id": session_id, "idempotency_key": f"{run.run_id.lower()}-f03-{mode}", "http_status": response.status_code, "detail": detail, "trace_id": trace_id, "failed_model_calls": [{"agent_id": item.get("agent_id"), "status": item.get("status"), "trace_id": item.get("trace_id"), "error_type": item.get("error_type")} for item in calls if isinstance(item, dict)], "task_ids_before": sorted(str(item.get("id")) for item in tasks_before if isinstance(item, dict)), "task_ids_after": sorted(str(item.get("id")) for item in tasks_after if isinstance(item, dict)), "circuit_breaker": diagnostics.get("circuit_breaker")}
    if detail.get("code") != "TASK_DECOMPOSITION_FAILED" or not trace_id or payload["task_ids_before"] != payload["task_ids_after"] or not any(item.get("status") == "FAILED" for item in payload["failed_model_calls"]):
        raise UATJourneyError(f"DeepSeek {mode} 探针缺少失败审计或产生了虚假任务")
    snapshot_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return snapshot_path


async def _run_uat_f03(api: _FormalClient, run: EvidenceRun, config: UATJourneyConfig) -> Path:
    admin = await api.login(config.admin_username, config.admin_password)
    snapshots = {mode: json.loads((run.path / "api" / f"f03-{mode}.json").read_text(encoding="utf-8")) for mode in ("unauthorized-1", "unauthorized-2", "timeout")}
    first = snapshots["unauthorized-1"]
    session_id = str(first.get("session_id") or "")
    retry = await api.request("POST", "/api/v1/admin/tasks/decompose", body={"goal": _task_decomposition_goal(), "session_id": session_id}, extra_headers={"Idempotency-Key": str(first.get("idempotency_key") or "")})
    tasks = _list_field(retry, "tasks")
    diagnostics = await api.request("GET", "/api/v1/admin/diagnostics")
    assertions = [
        _assertion("两个 401 与一个超时均明确失败且可追踪", all(snapshot.get("http_status") == 502 and _dict_field(snapshot, "detail").get("code") == "TASK_DECOMPOSITION_FAILED" and snapshot.get("trace_id") and snapshot.get("failed_model_calls") for snapshot in snapshots.values()), {"probes": [{"mode": mode, "trace_id": snapshot.get("trace_id"), "http_status": snapshot.get("http_status")} for mode, snapshot in snapshots.items()]}),
        _assertion("故障期不生成假任务且诊断进入熔断状态", all(snapshot.get("task_ids_before") == snapshot.get("task_ids_after") for snapshot in snapshots.values()) and _dict_field(snapshots["timeout"], "circuit_breaker").get("state") == "OPEN", {"circuit": snapshots["timeout"].get("circuit_breaker"), "unchanged_task_counts": [len(snapshot.get("task_ids_before") or []) for snapshot in snapshots.values()]}),
        _assertion("恢复真实 DeepSeek 后原业务动作可用同一幂等键重试", len(tasks) == 4 and bool(retry.get("decomposition_id")) and _dict_field(diagnostics, "circuit_breaker").get("state") == "CLOSED", {"decomposition_id": retry.get("decomposition_id"), "task_count": len(tasks), "circuit": diagnostics.get("circuit_breaker")}),
    ]
    evidence = {"business_ids": {"venue_id": str(admin.get("venue_id") or ""), "session_id": session_id, "decomposition_id": str(retry.get("decomposition_id") or ""), "failure_trace_id": str(first.get("trace_id") or "")}, "references": ["POST /api/v1/admin/tasks/decompose", "GET /api/v1/admin/llm-calls", "GET /api/v1/admin/diagnostics"], "assertions": assertions, "model_calls": [], "artifacts": {"unauthorized-1": snapshots["unauthorized-1"], "unauthorized-2": snapshots["unauthorized-2"], "timeout": snapshots["timeout"], "recovered-decomposition": retry, "diagnostics-after": diagnostics}}
    return _record_step_result(run, "UAT-F03", passed=all(item["passed"] for item in assertions), evidence=evidence)


async def _run_uat_f08(api: _FormalClient, run: EvidenceRun, config: UATJourneyConfig) -> Path:
    admin = await api.login(config.admin_username, config.admin_password)
    prior = json.loads((run.path / "steps" / "UAT-F07.json").read_text(encoding="utf-8"))
    interview_id = str(_dict_field(prior, "business_ids").get("interview_id") or "")
    if not interview_id:
        raise UATJourneyError("UAT-F08 缺少恢复后的访谈")
    expert_api = _FormalClient(api._client)
    await expert_api.login("zhang-jianguo", config.employee_password)
    interview = _dict_field(await expert_api.request("GET", f"/api/v1/assistant/experience/interviews/{interview_id}"), "interview")
    if interview.get("status") != "IN_PROGRESS" or _dict_field(interview, "progress").get("answered") != 2:
        raise UATJourneyError("UAT-F08 需要同一 run 中尚余两题的真实专家访谈")
    answers = (
        "持续金属摩擦、制动跑偏、裂纹或轮端异常温升任一出现，都必须停运并升级设备主管，绝不能载客试车。",
        "仅适用于悦山景区雨后涉水观光车轮端异常；必须保留停运、检修、三轮空载试车与经理审批证据，其他车型另行评估。",
    )
    for number, answer in enumerate(answers, start=3):
        await expert_api.request("POST", f"/api/v1/assistant/experience/interviews/{interview_id}/answers", body={"answer": answer}, extra_headers={"Idempotency-Key": f"{run.run_id.lower()}-f08-answer-{number}"})
    completed = await expert_api.request("POST", f"/api/v1/assistant/experience/interviews/{interview_id}/complete")
    card_id = str(_dict_field(completed, "card").get("id") or "")
    if not card_id:
        raise UATJourneyError("UAT-F08 访谈完成后没有生成经验卡")
    confirmed = _dict_field(await expert_api.request("POST", f"/api/v1/assistant/experience/cards/{card_id}/confirm"), "card")
    submitted = _dict_field(await api.request("POST", f"/api/v1/admin/experience-cards/{card_id}/submit"), "card")
    docker = _IsolatedDocker()
    stopped = await docker.stop()
    try:
        failure = await api.expect_rejection("POST", f"/api/v1/admin/experience-cards/{card_id}/publish", body={"comment": "验证索引故障时不发布"}, expected_statuses=(503,))
        failed_detail = _dict_field(await api.request("GET", f"/api/v1/admin/experience-cards/{card_id}"), "experience_card")
    finally:
        restored = await docker.start()
    published = _dict_field(await api.request("POST", f"/api/v1/admin/experience-cards/{card_id}/publish", body={"comment": "索引服务恢复后发布"}), "card")
    final_detail = _dict_field(await api.request("GET", f"/api/v1/admin/experience-cards/{card_id}"), "experience_card")
    assertions = [
        _assertion("重启恢复的专家访谈完成并生成待审核卡片", _dict_field(completed, "card").get("source_interview_id") == interview_id and confirmed.get("status") == "EXPERT_CONFIRMED" and submitted.get("status") == "IN_REVIEW", {"interview_id": interview_id, "card_id": card_id, "submitted_status": submitted.get("status")}),
        _assertion("TEI 停止时发布失败且数据库未假发布", stopped["stopped"].get("running") is False and failure.get("status_code") == 503 and _dict_field(failure, "detail").get("code") == "EXPERIENCE_INDEX_WRITE_FAILED" and failed_detail.get("status") == "IN_REVIEW" and failed_detail.get("index_status") == "NOT_INDEXED" and not failed_detail.get("vector_doc_id"), {"failure": failure, "status": failed_detail.get("status"), "index_status": failed_detail.get("index_status"), "vector_doc_id": failed_detail.get("vector_doc_id")}),
        _assertion("TEI 恢复后同一版本成功发布并建立索引", restored.get("health") == "healthy" and published.get("status") == "PUBLISHED" and final_detail.get("index_status") == "INDEXED" and final_detail.get("vector_doc_id") == f"experience:venue-yueshan:{card_id}:v1", {"health": restored.get("health"), "status": final_detail.get("status"), "index_status": final_detail.get("index_status"), "vector_doc_id": final_detail.get("vector_doc_id")}),
    ]
    evidence = {"business_ids": {"venue_id": str(admin.get("venue_id") or ""), "interview_id": interview_id, "experience_card_id": card_id, "vector_doc_id": str(final_detail.get("vector_doc_id") or "")}, "references": [f"POST /api/v1/assistant/experience/interviews/{interview_id}/complete", f"POST /api/v1/admin/experience-cards/{card_id}/publish", f"GET /api/v1/admin/experience-cards/{card_id}", "Docker Engine /containers/tei-embedding/stop", "Docker Engine /containers/tei-embedding/start"], "assertions": assertions, "model_calls": [], "artifacts": {"completed-interview": completed, "confirmed-card": confirmed, "submitted-card": submitted, "tei-stopped": stopped, "publish-failure": failure, "card-after-failure": failed_detail, "tei-restored": restored, "published-card": published, "card-final": final_detail}}
    return _record_step_result(run, "UAT-F08", passed=all(item["passed"] for item in assertions), evidence=evidence)


async def _run_uat_f10(api: _FormalClient, run: EvidenceRun, config: UATJourneyConfig) -> Path:
    if len(config.employee_password) < 12:
        raise UATJourneyError("UAT-F10 要求 UAT_EMPLOYEE_PASSWORD 至少 12 位")
    admin = await api.login(config.admin_username, config.admin_password)
    foreign_venue_id = f"venue-uat-foreign-{run.run_id[-8:].lower()}"
    venue = _dict_field(await api.request("POST", "/api/v1/admin/venues", body={"id": foreign_venue_id, "name": "UAT 跨场地隔离验证区"}), "venue")
    username = f"uat-foreign-{run.run_id[-8:].lower()}"
    user = _dict_field(await api.request("POST", "/api/v1/admin/users", body={"username": username, "password": config.employee_password, "display_name": "跨场地测试经理", "role": "manager", "venue_id": foreign_venue_id}), "user")
    foreign_api = _FormalClient(api._client)
    foreign = await foreign_api.login(username, config.employee_password)
    event_id = str(_dict_field(json.loads((run.path / "steps" / "E2E-12.json").read_text(encoding="utf-8")), "business_ids").get("event_id") or "")
    task_id = str(_e2e_05_tasks(run)[0]["id"])
    approval_id = str(_dict_field(json.loads((run.path / "steps" / "E2E-09.json").read_text(encoding="utf-8")), "business_ids").get("approval_id") or "")
    card_id = str(_dict_field(json.loads((run.path / "steps" / "E2E-14.json").read_text(encoding="utf-8")), "business_ids").get("experience_card_id") or "")
    session_id = str(_dict_field(json.loads((run.path / "steps" / "E2E-02.json").read_text(encoding="utf-8")), "business_ids").get("session_id") or "")
    denied = {
        "event": await foreign_api.expect_rejection("GET", f"/api/v1/admin/events/{event_id}", expected_statuses=(404,)),
        "task": await foreign_api.expect_rejection("GET", f"/api/v1/admin/tasks/{task_id}", expected_statuses=(404,)),
        "approval": await foreign_api.expect_rejection("GET", f"/api/v1/admin/approvals/{approval_id}", expected_statuses=(404,)),
        "experience": await foreign_api.expect_rejection("GET", f"/api/v1/admin/experience-cards/{card_id}", expected_statuses=(404,)),
        "session": await foreign_api.expect_rejection("GET", f"/api/v1/assistant/sessions/{session_id}/messages", expected_statuses=(403, 404)),
    }
    assertions = [
        _assertion("测试经理属于独立正式场地", venue.get("id") == foreign_venue_id and user.get("id") == foreign.get("id") and foreign.get("venue_id") == foreign_venue_id and foreign.get("role") == "manager", {"venue_id": foreign.get("venue_id"), "role": foreign.get("role")}),
        _assertion("跨场地事件、任务、审批和经验读取均拒绝", all(item.get("status_code") == 404 for key, item in denied.items() if key != "session"), denied),
        _assertion("跨场地会话内容在读取前拒绝", denied["session"].get("status_code") in {403, 404}, denied["session"]),
    ]
    evidence = {"business_ids": {"venue_id": str(admin.get("venue_id") or ""), "foreign_venue_id": foreign_venue_id, "foreign_user_id": str(user.get("id") or ""), "event_id": event_id, "experience_card_id": card_id}, "references": ["POST /api/v1/admin/venues", "POST /api/v1/admin/users", "POST /api/v1/auth/login", f"GET /api/v1/admin/events/{event_id}", f"GET /api/v1/admin/tasks/{task_id}", f"GET /api/v1/admin/experience-cards/{card_id}"], "assertions": assertions, "model_calls": [], "artifacts": {"foreign-principal": foreign, "authorization-rejections": denied}}
    return _record_step_result(run, "UAT-F10", passed=all(item["passed"] for item in assertions), evidence=evidence)


async def _run_uat_f07(api: _FormalClient, run: EvidenceRun, config: UATJourneyConfig) -> Path:
    before_path = run.path / "api" / "interview-before-restart.json"
    if not before_path.is_file():
        raise UATJourneyError("UAT-F07 缺少重启前访谈快照")
    before = json.loads(before_path.read_text(encoding="utf-8"))
    interview_id = str(before.get("interview_id") or "")
    expert_api = _FormalClient(api._client)
    principal = await expert_api.login("zhang-jianguo", config.employee_password)
    restored = _dict_field(await expert_api.request("GET", f"/api/v1/assistant/experience/interviews/{interview_id}"), "interview")
    diagnostics_api = _FormalClient(api._client)
    await diagnostics_api.login(config.admin_username, config.admin_password)
    diagnostics = await diagnostics_api.request("GET", "/api/v1/admin/diagnostics")
    after_instance = str(_dict_field(_dict_field(diagnostics, "runtime"), "app").get("instance_id") or "")
    resumed = _dict_field(await expert_api.request("POST", f"/api/v1/assistant/experience/interviews/{interview_id}/resume"), "interview")
    replay = await expert_api.request("POST", f"/api/v1/assistant/experience/interviews/{interview_id}/answers", body={"answer": before["first_answer"]}, extra_headers={"Idempotency-Key": before["first_idempotency_key"]})
    next_answer = await expert_api.request("POST", f"/api/v1/assistant/experience/interviews/{interview_id}/answers", body={"answer": "先停运隔离和断电，完成轮端检修后再做三轮空载低速试车。"}, extra_headers={"Idempotency-Key": f"{run.run_id.lower()}-f07-second"})
    after = _dict_field(await expert_api.request("GET", f"/api/v1/assistant/experience/interviews/{interview_id}"), "interview")
    assertions = [
        _assertion("访谈期间 App 运行实例真实变化", bool(after_instance) and after_instance != before.get("instance_id") and principal.get("username") == "zhang-jianguo", {"before_instance_id": before.get("instance_id"), "after_instance_id": after_instance}),
        _assertion("重启后暂停访谈和首轮回答完整恢复", restored.get("status") == "PAUSED" and restored.get("progress", {}).get("answered") == 1 and len(_list_field(restored, "turns")) == 1, {"status": restored.get("status"), "progress": restored.get("progress"), "turn_count": len(_list_field(restored, "turns"))}),
        _assertion("恢复后重复回答去重并可继续下一轮", resumed.get("status") == "IN_PROGRESS" and replay.get("idempotent_replay") is True and _dict_field(next_answer, "turn").get("turn_number") == 2 and after.get("progress", {}).get("answered") == 2 and len(_list_field(after, "turns")) == 2, {"replay": replay.get("idempotent_replay"), "answered": after.get("progress", {}).get("answered"), "turn_count": len(_list_field(after, "turns"))}),
    ]
    evidence = {"business_ids": {"venue_id": str(principal.get("venue_id") or ""), "interview_id": interview_id, "before_instance_id": str(before.get("instance_id") or ""), "after_instance_id": after_instance}, "references": [f"GET /api/v1/assistant/experience/interviews/{interview_id}", f"POST /api/v1/assistant/experience/interviews/{interview_id}/resume", f"POST /api/v1/assistant/experience/interviews/{interview_id}/answers", "GET /api/v1/admin/diagnostics", "docker compose up --force-recreate app"], "assertions": assertions, "model_calls": [], "artifacts": {"before-restart": before, "restored": restored, "replayed-answer": replay, "second-answer": next_answer, "after": after}}
    return _record_step_result(run, "UAT-F07", passed=all(item["passed"] for item in assertions), evidence=evidence)


async def _run_uat_f09(api: _FormalClient, run: EvidenceRun, config: UATJourneyConfig) -> Path:
    admin = await api.login(config.admin_username, config.admin_password)
    identities = _list_field(await api.request("GET", "/api/v1/channels/simulator-identities"), "identities")
    reporter = next((item for item in identities if isinstance(item, dict) and item.get("username") == "zhou-qi"), {})
    user_id = str(reporter.get("user_id") or "")
    if not user_id:
        raise UATJourneyError("UAT-F09 缺少周琪内部接入身份")
    accepted = await api.request("POST", "/api/v1/channels/simulator/messages", body={"user_id": user_id, "content": "UAT 新事件：北门备用观光车出现异常制动噪声，车辆已停运断电，检修任务尚未完成，请记录事件。", "external_message_id": f"{run.run_id.lower()}-f09", "external_conversation_id": f"{run.run_id.lower()}-f09-zhou"})
    trace_id = str(accepted.get("trace_id") or "")
    trace: dict[str, Any] = {}
    for _attempt in range(30):
        trace = await api.request("GET", f"/api/v1/admin/traces/{trace_id}")
        if _dict_field(trace, "message_run").get("status") in {"COMPLETED", "FAILED"}:
            break
        await asyncio.sleep(2)
    events = _list_field(await api.request("GET", "/api/v1/admin/events"), "events")
    event = next((item for item in events if isinstance(item, dict) and item.get("trace_id") == trace_id), {})
    event_id = str(event.get("event_id") or "")
    if not event_id:
        raise UATJourneyError("UAT-F09 消息未创建可检查事件")
    task = _dict_field(await api.request("POST", "/api/v1/admin/tasks", body={"session_id": accepted.get("session_id"), "event_id": event_id, "description": "检查备用观光车异常制动噪声并回填结果"}), "task")
    task_id = str(task.get("id") or "")
    first = await api.request("POST", f"/api/v1/admin/events/{event_id}/watcher-check")
    second = await api.request("POST", f"/api/v1/admin/events/{event_id}/watcher-check")
    first_task_finding = next((item for item in _list_field(first, "findings") if isinstance(item, dict) and item.get("source_id") == task_id), {})
    second_task_finding = next((item for item in _list_field(second, "findings") if isinstance(item, dict) and item.get("source_id") == task_id and item.get("id") == first_task_finding.get("id")), {})
    assertions = [
        _assertion("独立新事件与未完成任务通过正式入口创建", _dict_field(trace, "message_run").get("status") == "COMPLETED" and event.get("status") == "OPEN" and task.get("status") == "PENDING", {"event_id": event_id, "task_id": task_id, "task_status": task.get("status")}),
        _assertion("Watcher 两次实际运行均发现相同任务闭环阻断", bool(first_task_finding) and bool(second_task_finding) and first.get("ready_to_close") is False and second.get("ready_to_close") is False, {"first_run_id": _dict_field(first, "run").get("id"), "second_run_id": _dict_field(second, "run").get("id"), "finding_id": first_task_finding.get("id")}),
        _assertion("重复运行复用原 finding 而非生成副本", second_task_finding.get("reused") is True and second_task_finding.get("id") == first_task_finding.get("id"), {"first_id": first_task_finding.get("id"), "second_id": second_task_finding.get("id"), "reused": second_task_finding.get("reused")}),
    ]
    evidence = {"business_ids": {"venue_id": str(admin.get("venue_id") or ""), "event_id": event_id, "task_id": task_id, "trace_id": trace_id, "finding_id": str(first_task_finding.get("id") or "missing-finding")}, "references": ["POST /api/v1/channels/simulator/messages", "POST /api/v1/admin/tasks", f"POST /api/v1/admin/events/{event_id}/watcher-check"], "assertions": assertions, "model_calls": [], "artifacts": {"message": accepted, "task": task, "first-watcher": first, "second-watcher": second}}
    return _record_step_result(run, "UAT-F09", passed=all(item["passed"] for item in assertions), evidence=evidence)


async def _run_uat_f06(api: _FormalClient, run: EvidenceRun, config: UATJourneyConfig) -> Path:
    admin = await api.login(config.admin_username, config.admin_password)
    prior = json.loads((run.path / "steps" / "UAT-F09.json").read_text(encoding="utf-8"))
    prior_ids = _dict_field(prior, "business_ids")
    message = json.loads((run.path / "artifacts" / "UAT-F09" / "message.json").read_text(encoding="utf-8"))
    event_id = str(prior_ids.get("event_id") or "")
    task_id = str(prior_ids.get("task_id") or "")
    session_id = str(message.get("session_id") or "")
    identities = _list_field(await api.request("GET", "/api/v1/channels/simulator-identities"), "identities")
    recipient = next((item for item in identities if isinstance(item, dict) and item.get("username") == "zhou-qi"), {})
    user_id = str(recipient.get("user_id") or "")
    tenant_id = str(recipient.get("external_tenant_id") or "")
    external_user_id = str(recipient.get("external_user_id") or "")
    if not all((event_id, task_id, session_id, user_id, tenant_id, external_user_id)):
        raise UATJourneyError("UAT-F06 缺少同一事件的任务、会话或周琪接入身份")
    approval_request = await api.request(
        "POST", "/api/v1/admin/action-requests",
        body={"action_code": "SEND_CRITICAL_DISPATCH_ALERT", "session_id": session_id, "event_id": event_id, "task_id": task_id, "message": "UAT 审批并发及接入身份故障验证：车辆继续停运。"},
        extra_headers={"Idempotency-Key": f"{run.run_id.lower()}-f06-failure-v2"},
    )
    approval_id = str(approval_request.get("approval_id") or "")
    if not approval_id:
        raise UATJourneyError("UAT-F06 未创建待审批单")
    identity_body = {"channel": "WECOM_SIMULATOR", "external_tenant_id": tenant_id, "external_user_id": external_user_id, "user_id": user_id}
    disabled = await api.request("POST", "/api/v1/channels/identities", body={**identity_body, "status": "DISABLED"})
    try:
        first, second = await asyncio.gather(
            api._client.post(f"/api/v1/admin/approvals/{approval_id}/approve", json={"comment": "并发审批故障注入"}, headers={"Authorization": f"Bearer {api._access_token}"}),
            api._client.post(f"/api/v1/admin/approvals/{approval_id}/approve", json={"comment": "并发审批故障注入"}, headers={"Authorization": f"Bearer {api._access_token}"}),
        )
        failed_approval = await api.request("GET", f"/api/v1/admin/approvals/{approval_id}")
    finally:
        restored = await api.request("POST", "/api/v1/channels/identities", body={**identity_body, "status": "ACTIVE"})
    outbox_after = await api.request("GET", f"/api/v1/channels/simulator/sessions/{session_id}/outbox", params={"user_id": user_id})
    response_codes = sorted((first.status_code, second.status_code))
    delivered_after = [item for item in _list_field(outbox_after, "items") if isinstance(item, dict) and item.get("approval_id") == approval_id and item.get("delivery_status") == "DELIVERED"]
    assertions = [
        _assertion("并发审批只有一次成功领取终态", response_codes == [200, 404], {"http_statuses": response_codes}),
        _assertion("失效身份使已批准动作显式执行失败", disabled.get("status") == "DISABLED" and failed_approval.get("status") == "APPROVED" and failed_approval.get("execution_status") == "FAILED" and bool(failed_approval.get("execution_error")), {"approval_status": failed_approval.get("status"), "execution_status": failed_approval.get("execution_status"), "execution_error": failed_approval.get("execution_error")}),
        _assertion("动作失败不产生已送达通知且测试身份恢复", not delivered_after and restored.get("status") == "ACTIVE", {"delivered_count": len(delivered_after), "restored_status": restored.get("status")}),
    ]
    evidence = {"business_ids": {"venue_id": str(admin.get("venue_id") or ""), "event_id": event_id, "task_id": task_id, "approval_id": approval_id, "recipient_user_id": user_id}, "references": ["POST /api/v1/admin/action-requests", f"POST /api/v1/admin/approvals/{approval_id}/approve", f"GET /api/v1/admin/approvals/{approval_id}", "POST /api/v1/channels/identities"], "assertions": assertions, "model_calls": [], "artifacts": {"approval-request": approval_request, "failed-approval": failed_approval, "outbox-after": outbox_after, "disabled-identity": disabled, "restored-identity": restored}}
    return _record_step_result(run, "UAT-F06", passed=all(item["passed"] for item in assertions), evidence=evidence)


async def _run_uat_f05(
    api: _FormalClient,
    run: EvidenceRun,
    config: UATJourneyConfig,
) -> Path:
    admin = await api.login(config.admin_username, config.admin_password)
    session_id = f"uat-dependency-{run.run_id[-8:].lower()}"
    parent_payload = await api.request(
        "POST",
        "/api/v1/admin/tasks",
        body={"session_id": session_id, "description": "UAT 前置检修任务"},
    )
    parent = _dict_field(parent_payload, "task")
    parent_id = str(parent.get("id") or "")
    if not parent_id:
        raise UATJourneyError("UAT-F05 前置任务缺少正式 ID")
    child_payload = await api.request(
        "POST",
        "/api/v1/admin/tasks",
        body={
            "session_id": session_id,
            "description": "UAT 依赖完成后的复运任务",
            "dependencies": [parent_id],
        },
    )
    child = _dict_field(child_payload, "task")
    child_id = str(child.get("id") or "")
    if not child_id:
        raise UATJourneyError("UAT-F05 后续任务缺少正式 ID")
    rejection = await api.expect_rejection(
        "POST", f"/api/v1/admin/tasks/{child_id}/start", expected_statuses=(409,)
    )
    blocked_payload = await api.request("GET", f"/api/v1/admin/tasks/{child_id}")
    blocked = _dict_field(blocked_payload, "task")
    started_parent_payload = await api.request("POST", f"/api/v1/admin/tasks/{parent_id}/start")
    started_parent = _dict_field(started_parent_payload, "task")
    completed_parent_payload = await api.request(
        "POST",
        f"/api/v1/admin/tasks/{parent_id}/complete",
        body={"result": {"summary": "已完成前置检修并提交 UAT 结果"}},
    )
    completed_parent = _dict_field(completed_parent_payload, "task")
    started_child_payload = await api.request("POST", f"/api/v1/admin/tasks/{child_id}/start")
    started_child = _dict_field(started_child_payload, "task")
    assertions = [
        _assertion("后续任务持久化前置依赖", child.get("dependencies") == [parent_id], child),
        _assertion("前置未完成时启动被拒绝且状态不变", rejection.get("status_code") == 409 and blocked.get("status") == "BLOCKED", {"rejection": rejection, "status": blocked.get("status")}),
        _assertion("前置任务经正式接口启动并完成", started_parent.get("status") == "RUNNING" and completed_parent.get("status") == "DONE", {"started": started_parent.get("status"), "completed": completed_parent.get("status")}),
        _assertion("依赖完成后后续任务可启动", started_child.get("status") == "RUNNING", {"status": started_child.get("status")}),
    ]
    evidence = {
        "business_ids": {"venue_id": str(admin.get("venue_id") or ""), "session_id": session_id, "parent_task_id": parent_id, "child_task_id": child_id},
        "references": ["POST /api/v1/admin/tasks", f"POST /api/v1/admin/tasks/{child_id}/start", f"POST /api/v1/admin/tasks/{parent_id}/complete", f"GET /api/v1/admin/tasks/{child_id}"],
        "assertions": assertions,
        "model_calls": [],
        "artifacts": {"parent-created": parent, "child-created": child, "blocked-attempt": rejection, "child-blocked": blocked, "parent-completed": completed_parent, "child-started": started_child},
    }
    return _record_step_result(run, "UAT-F05", passed=all(item["passed"] for item in assertions), evidence=evidence)


async def _run_uat_f11(api: _FormalClient, run: EvidenceRun, config: UATJourneyConfig) -> Path:
    if len(config.employee_password) < 12:
        raise UATJourneyError("UAT-F11 要求 UAT_EMPLOYEE_PASSWORD 至少 12 位")
    employee_api = _FormalClient(api._client)
    employee = await employee_api.login("li-ming", config.employee_password)
    rejected = {
        "users": await employee_api.expect_rejection("GET", "/api/v1/admin/users", expected_statuses=(403,)),
        "diagnostics": await employee_api.expect_rejection("GET", "/api/v1/admin/diagnostics", expected_statuses=(403,)),
        "assignees": await employee_api.expect_rejection("GET", "/api/v1/admin/assignees", expected_statuses=(403,)),
        "task_creation": await employee_api.expect_rejection("POST", "/api/v1/admin/tasks", body={"session_id": f"uat-denied-{run.run_id[-8:].lower()}", "description": "员工越权创建任务应被拒绝"}, expected_statuses=(403,)),
    }
    assertions = [
        _assertion("普通员工使用独立正式账号", employee.get("role") == "operator" and employee.get("username") == "li-ming", {"role": employee.get("role"), "username": employee.get("username")}),
        _assertion("员工读取用户、诊断和治理目录均被拒绝", all(item.get("status_code") == 403 for item in rejected.values()), rejected),
    ]
    evidence = {
        "business_ids": {"venue_id": str(employee.get("venue_id") or ""), "employee_user_id": str(employee.get("id") or "")},
        "references": ["POST /api/v1/auth/login", "GET /api/v1/admin/users", "GET /api/v1/admin/diagnostics", "GET /api/v1/admin/assignees", "POST /api/v1/admin/tasks"],
        "assertions": assertions,
        "model_calls": [],
        "artifacts": {"employee-principal": employee, "authorization-rejections": rejected},
    }
    return _record_step_result(run, "UAT-F11", passed=all(item["passed"] for item in assertions), evidence=evidence)


async def _run_uat_f12(api: _FormalClient, run: EvidenceRun, config: UATJourneyConfig) -> Path:
    admin = await api.login(config.admin_username, config.admin_password)
    integrations_payload = await api.request("GET", "/api/v1/admin/integrations")
    integrations = {str(item.get("id")): item for item in _list_field(integrations_payload, "integrations") if isinstance(item, dict)}
    diagnostics = await api.request("GET", "/api/v1/admin/diagnostics")
    channels = _dict_field(diagnostics, "channels")
    real_wecom = _dict_field(channels, "real_wecom")
    simulator = _dict_field(channels, "wecom_simulator")
    assertions = [
        _assertion("真实企业微信由策略禁用且未初始化或投递", integrations.get("wechat", {}).get("status") == "DISABLED_BY_POLICY" and integrations.get("wechat", {}).get("safe_disabled_verified") is True and real_wecom.get("status") == "DISABLED_BY_POLICY" and real_wecom.get("client_initialized") is False and real_wecom.get("delivery_enabled") is False, {"integration_status": integrations.get("wechat", {}).get("status"), "runtime": real_wecom}),
        _assertion("短信和语音未配置且安全禁用", all(integrations.get(name, {}).get("status") == "DISABLED_REQUIRES_CONFIG" and integrations.get(name, {}).get("safe_disabled_verified") is True for name in ("sms", "voice")), {"sms": integrations.get("sms"), "voice": integrations.get("voice")}),
        _assertion("内部模拟渠道仍可用", simulator.get("status") == "SIMULATOR_READY" and integrations.get("wecom_simulator", {}).get("status") == "SIMULATOR_READY", {"runtime": simulator}),
    ]
    evidence = {
        "business_ids": {"venue_id": str(admin.get("venue_id") or "")},
        "references": ["GET /api/v1/admin/integrations", "GET /api/v1/admin/diagnostics"],
        "assertions": assertions,
        "model_calls": [],
        "artifacts": {"integration-statuses": integrations_payload, "channel-diagnostics": channels},
    }
    return _record_step_result(run, "UAT-F12", passed=all(item["passed"] for item in assertions), evidence=evidence)


async def _run_uat_f13(api: _FormalClient, run: EvidenceRun, config: UATJourneyConfig) -> Path:
    if len(config.employee_password) < 12:
        raise UATJourneyError("UAT-F13 要求 UAT_EMPLOYEE_PASSWORD 至少 12 位")
    admin = await api.login(config.admin_username, config.admin_password)
    username = f"uat-unbound-{run.run_id[-8:].lower()}"
    created_payload = await api.request(
        "POST", "/api/v1/admin/users",
        body={"username": username, "password": config.employee_password, "display_name": "UAT 未绑定员工", "role": "operator", "venue_id": admin.get("venue_id")},
    )
    user = _dict_field(created_payload, "user")
    user_id = str(user.get("id") or "")
    if not user_id:
        raise UATJourneyError("UAT-F13 新员工缺少正式 ID")
    message = {
        "user_id": user_id,
        "content": "UAT 未绑定身份消息，应在创建业务记录前被拒绝",
        "external_message_id": f"{run.run_id.lower()}-f13-unbound",
        "external_conversation_id": f"{run.run_id.lower()}-f13",
    }
    unbound = await api.expect_rejection("POST", "/api/v1/channels/simulator/messages", body=message, expected_statuses=(403,))
    identity_payload = await api.request(
        "POST", "/api/v1/channels/identities",
        body={"channel": "WECOM_SIMULATOR", "external_tenant_id": "wecom-yueshan", "external_user_id": f"wecom-{username}", "user_id": user_id, "status": "DISABLED"},
    )
    disabled_message = {**message, "external_message_id": f"{run.run_id.lower()}-f13-disabled"}
    disabled = await api.expect_rejection("POST", "/api/v1/channels/simulator/messages", body=disabled_message, expected_statuses=(403,))
    sessions_payload = await api.request("GET", "/api/v1/assistant/sessions", params={"acting_user_id": user_id})
    assertions = [
        _assertion("有正式用户但无渠道映射时消息被拒绝", unbound.get("status_code") == 403 and _dict_field(unbound, "detail").get("code") == "IDENTITY_NOT_BOUND", unbound),
        _assertion("停用渠道映射仍不能进入受理链", identity_payload.get("status") == "DISABLED" and disabled.get("status_code") == 403 and _dict_field(disabled, "detail").get("code") == "IDENTITY_NOT_BOUND", {"identity_status": identity_payload.get("status"), "rejection": disabled}),
        _assertion("两次拒绝均未创建员工会话", not _list_field(sessions_payload, "sessions"), {"session_count": len(_list_field(sessions_payload, "sessions"))}),
    ]
    evidence = {
        "business_ids": {"venue_id": str(admin.get("venue_id") or ""), "employee_user_id": user_id, "identity_id": str(identity_payload.get("id") or "missing-identity")},
        "references": ["POST /api/v1/admin/users", "POST /api/v1/channels/simulator/messages", "POST /api/v1/channels/identities", "GET /api/v1/assistant/sessions"],
        "assertions": assertions,
        "model_calls": [],
        "artifacts": {"employee": user, "unbound-rejection": unbound, "disabled-binding": identity_payload, "disabled-rejection": disabled, "sessions": sessions_payload},
    }
    return _record_step_result(run, "UAT-F13", passed=all(item["passed"] for item in assertions), evidence=evidence)


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


async def prepare_uat_restart(config: UATJourneyConfig, run: EvidenceRun) -> Path:
    if "E2E-15" not in _passed_step_ids(run):
        raise UATJourneyError("重启准备要求同一证据包中的 E2E-15 已通过")
    snapshot_path = run.path / "api" / "runtime-before.json"
    if snapshot_path.exists():
        raise FileExistsError("重启前运行快照已存在")
    origin = json.loads((run.path / "steps" / "E2E-02.json").read_text(encoding="utf-8"))
    session_id = str(_dict_field(origin, "business_ids").get("session_id") or "")
    async with httpx.AsyncClient(base_url=config.base_url, timeout=config.timeout_seconds, trust_env=False) as client:
        api = _FormalClient(client)
        await api.login(config.admin_username, config.admin_password)
        task = _dict_field(await api.request("POST", "/api/v1/admin/tasks", body={"session_id": session_id, "description": "UAT App 重启前保持执行中的恢复任务"}), "task")
        task_id = str(task.get("id") or "")
        running = _dict_field(await api.request("POST", f"/api/v1/admin/tasks/{task_id}/start"), "task")
        diagnostics = await api.request("GET", "/api/v1/admin/diagnostics")
        queue = await api.request("GET", "/api/v1/admin/queue")
    if running.get("status") != "RUNNING" or not _dict_field(_dict_field(diagnostics, "runtime"), "app").get("instance_id"):
        raise UATJourneyError("重启前任务或运行实例未准备就绪")
    payload = {"runtime": diagnostics.get("runtime"), "runtime_identity": diagnostics.get("runtime_identity"), "queue": queue, "uat_recovery_task": running}
    temporary = snapshot_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(snapshot_path)
    return snapshot_path


async def prepare_uat_interview_restart(config: UATJourneyConfig, run: EvidenceRun) -> Path:
    if "E2E-16" not in _passed_step_ids(run):
        raise UATJourneyError("访谈重启准备要求 E2E-16 已通过")
    snapshot_path = run.path / "api" / "interview-before-restart.json"
    if snapshot_path.exists():
        raise FileExistsError("访谈重启前快照已存在")
    prior = json.loads((run.path / "steps" / "E2E-13.json").read_text(encoding="utf-8"))
    prior_ids = _dict_field(prior, "business_ids")
    async with httpx.AsyncClient(base_url=config.base_url, timeout=config.timeout_seconds, trust_env=False) as client:
        api = _FormalClient(client)
        await api.login(config.admin_username, config.admin_password)
        invited = _dict_field(await api.request("POST", "/api/v1/admin/experience-interviews", body={"expert_id": prior_ids.get("expert_id"), "title": "UAT 重启恢复访谈", "source_event_id": prior_ids.get("event_id"), "authorization_scopes": [{"scope_type": "VENUE", "scope_value": "venue-yueshan"}]}), "interview")
        interview_id = str(invited.get("id") or "")
        expert_api = _FormalClient(client)
        await expert_api.login("zhang-jianguo", config.employee_password)
        await expert_api.request("POST", f"/api/v1/assistant/experience/interviews/{interview_id}/accept")
        first_answer = "雨后轮端摩擦声和水迹要停运检查，防尘护板间隙低于2毫米时不得载客。"
        first_key = f"{run.run_id.lower()}-f07-first"
        await expert_api.request("POST", f"/api/v1/assistant/experience/interviews/{interview_id}/answers", body={"answer": first_answer}, extra_headers={"Idempotency-Key": first_key})
        paused = _dict_field(await expert_api.request("POST", f"/api/v1/assistant/experience/interviews/{interview_id}/pause"), "interview")
        diagnostics = await api.request("GET", "/api/v1/admin/diagnostics")
    instance_id = str(_dict_field(_dict_field(diagnostics, "runtime"), "app").get("instance_id") or "")
    if paused.get("status") != "PAUSED" or paused.get("progress", {}).get("answered") != 1 or not instance_id:
        raise UATJourneyError("访谈未处于可重启恢复的暂停状态")
    payload = {"interview_id": interview_id, "first_answer": first_answer, "first_idempotency_key": first_key, "instance_id": instance_id, "status": paused.get("status"), "progress": paused.get("progress")}
    temporary = snapshot_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(snapshot_path)
    return snapshot_path


async def run_uat_steps(
    config: UATJourneyConfig,
    run: EvidenceRun,
    step_ids: Iterable[str],
    *,
    client: httpx.AsyncClient | None = None,
    attachment_path: Path | None = None,
    runtime_before_path: Path | None = None,
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
        trust_env=False,
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
            elif step_id == "E2E-03":
                if "E2E-02" not in _passed_step_ids(run):
                    raise UATJourneyError("E2E-03 要求同一证据包中的 E2E-02 已通过")
                recorded.append(await _run_e2e_03(api, run, config))
            elif step_id == "E2E-04":
                if "E2E-03" not in _passed_step_ids(run):
                    raise UATJourneyError("E2E-04 要求同一证据包中的 E2E-03 已通过")
                recorded.append(await _run_e2e_04(api, run, config))
            elif step_id == "E2E-05":
                if "E2E-04" not in _passed_step_ids(run):
                    raise UATJourneyError("E2E-05 要求同一证据包中的 E2E-04 已通过")
                recorded.append(await _run_e2e_05(api, run, config))
            elif step_id == "E2E-06":
                if "E2E-05" not in _passed_step_ids(run):
                    raise UATJourneyError("E2E-06 要求同一证据包中的 E2E-05 已通过")
                recorded.append(await _run_e2e_06(api, run, config))
            elif step_id == "E2E-07":
                if "E2E-06" not in _passed_step_ids(run):
                    raise UATJourneyError("E2E-07 要求同一证据包中的 E2E-06 已通过")
                recorded.append(await _run_e2e_07(api, run, config))
            elif step_id == "E2E-08":
                if "E2E-07" not in _passed_step_ids(run):
                    raise UATJourneyError("E2E-08 要求同一证据包中的 E2E-07 已通过")
                recorded.append(await _run_e2e_08(api, run, config))
            elif step_id == "E2E-09":
                if "E2E-08" not in _passed_step_ids(run):
                    raise UATJourneyError("E2E-09 要求同一证据包中的 E2E-08 已通过")
                recorded.append(await _run_e2e_09(api, run, config))
            elif step_id == "E2E-10":
                if "E2E-09" not in _passed_step_ids(run):
                    raise UATJourneyError("E2E-10 要求同一证据包中的 E2E-09 已通过")
                recorded.append(await _run_e2e_10(api, run, config))
            elif step_id == "E2E-11":
                if "E2E-10" not in _passed_step_ids(run):
                    raise UATJourneyError("E2E-11 要求同一证据包中的 E2E-10 已通过")
                recorded.append(await _run_e2e_11(api, run, config))
            elif step_id == "E2E-12":
                if "E2E-11" not in _passed_step_ids(run):
                    raise UATJourneyError("E2E-12 要求同一证据包中的 E2E-11 已通过")
                recorded.append(await _run_e2e_12(api, run, config))
            elif step_id == "E2E-13":
                if "E2E-12" not in _passed_step_ids(run):
                    raise UATJourneyError("E2E-13 要求同一证据包中的 E2E-12 已通过")
                recorded.append(await _run_e2e_13(api, run, config))
            elif step_id == "E2E-14":
                if "E2E-13" not in _passed_step_ids(run):
                    raise UATJourneyError("E2E-14 要求同一证据包中的 E2E-13 已通过")
                recorded.append(await _run_e2e_14(api, run, config))
            elif step_id == "E2E-15":
                if "E2E-14" not in _passed_step_ids(run):
                    raise UATJourneyError("E2E-15 要求同一证据包中的 E2E-14 已通过")
                recorded.append(await _run_e2e_15(api, run, config))
            elif step_id == "E2E-16":
                recorded.append(await _run_e2e_16(api, run, config, runtime_before_path))
            elif step_id == "UAT-F01":
                if not {"E2E-02", "E2E-05"}.issubset(_passed_step_ids(run)):
                    raise UATJourneyError("UAT-F01 要求消息和任务图已在同一证据包通过")
                recorded.append(await _run_uat_f01(api, run, config))
            elif step_id == "UAT-F04":
                if "E2E-14" not in _passed_step_ids(run):
                    raise UATJourneyError("UAT-F04 要求同一证据包中的 E2E-14 已通过")
                recorded.append(await _run_uat_f04(api, run, config))
            elif step_id == "UAT-F02":
                if "UAT-F09" not in _passed_step_ids(run):
                    raise UATJourneyError("UAT-F02 要求同一证据包中的 UAT-F09 已通过")
                recorded.append(await _run_uat_f02(api, run, config))
            elif step_id == "UAT-F03":
                recorded.append(await _run_uat_f03(api, run, config))
            elif step_id == "UAT-F10":
                if not {"E2E-09", "E2E-12", "E2E-14"}.issubset(_passed_step_ids(run)):
                    raise UATJourneyError("UAT-F10 要求同一证据包中的事件、审批和经验链已通过")
                recorded.append(await _run_uat_f10(api, run, config))
            elif step_id == "UAT-F07":
                recorded.append(await _run_uat_f07(api, run, config))
            elif step_id == "UAT-F08":
                if "UAT-F07" not in _passed_step_ids(run):
                    raise UATJourneyError("UAT-F08 要求同一证据包中的 UAT-F07 已通过")
                recorded.append(await _run_uat_f08(api, run, config))
            elif step_id == "UAT-F09":
                recorded.append(await _run_uat_f09(api, run, config))
            elif step_id == "UAT-F05":
                recorded.append(await _run_uat_f05(api, run, config))
            elif step_id == "UAT-F06":
                if "UAT-F09" not in _passed_step_ids(run):
                    raise UATJourneyError("UAT-F06 要求同一证据包中的 UAT-F09 已通过")
                recorded.append(await _run_uat_f06(api, run, config))
            elif step_id == "UAT-F11":
                recorded.append(await _run_uat_f11(api, run, config))
            elif step_id == "UAT-F12":
                recorded.append(await _run_uat_f12(api, run, config))
            elif step_id == "UAT-F13":
                recorded.append(await _run_uat_f13(api, run, config))
        return recorded
    finally:
        if owns_client:
            await active_client.aclose()
