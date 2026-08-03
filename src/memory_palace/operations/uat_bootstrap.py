"""Repeatable UAT master-data initialization through formal HTTP APIs only."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional

import httpx


UAT_ORGANIZATION_NAME = "悦山文旅集团"
UAT_VENUE_ID = "venue-yueshan"
UAT_VENUE_NAME = "悦山景区"
UAT_EXTERNAL_TENANT_ID = "wecom-yueshan"
UAT_SOP_TITLE = "观光车雨后复运与异常异响处置"
UAT_SOP_VERSION = "2.1"
UAT_SOP_CONTENT = """适用范围：悦山景区观光车在强降雨、积水或涉水后恢复运营前的安全检查。

一、立即隔离
1. 发现轮端金属摩擦声、制动跑偏、异常温升或涉水痕迹时，立即停车、断电、封存钥匙并设置警戒。
2. 未完成设备检修员检查和空载试车前，不得载客、不得投入运营。

二、检修检查
1. 检查轮端防尘护板与制动盘间隙，确认无变形、松动和持续摩擦。
2. 检查制动片、制动盘、轮毂、紧固件及涉水痕迹，并记录间隙、温度和现场照片。
3. 防尘护板间隙小于 2 毫米、存在持续摩擦、制动跑偏、裂纹或温度异常时，禁止继续试车并升级设备主管。

三、空载验证
1. 完成维修或校正后，在隔离区域进行三轮空载低速试车。
2. 每轮记录异响、制动表现、跑偏情况和结束温度；任何一项异常都应立即停止。

四、复运审批
设备检修证据和三轮试车记录齐全后，由当日值班经理审批复运。审批通过前车辆保持停运；必要时启用备用车辆并通知调度。"""
UAT_EXPERT_AUTHORIZATION_STATEMENT = (
    "张建国确认授权悦山文旅集团在悦山景区内部，将其设备检修访谈内容用于经验萃取、审核、发布和员工辅助决策；"
    "系统必须标注来源、保留审核记录，不得冒充本人实时答复，也不得超出授权范围对外传播。"
)


class UATBootstrapError(RuntimeError):
    """Raised when the formal UAT bootstrap cannot finish safely."""


@dataclass(frozen=True)
class UATBootstrapConfig:
    base_url: str
    admin_username: str
    admin_password: str = field(repr=False)
    employee_password: str = field(repr=False)
    timeout_seconds: float = 30.0

    @classmethod
    def from_environment(cls, environment: Optional[Mapping[str, str]] = None) -> "UATBootstrapConfig":
        values = os.environ if environment is None else environment
        base_url = values.get("MEMORY_PALACE_UAT_BASE_URL", "http://localhost:8000").strip()
        admin_username = values.get("ADMIN_USERNAME", "").strip().lower()
        admin_password = _read_environment_secret(values, "ADMIN_PASSWORD")
        employee_password = _read_environment_secret(values, "UAT_EMPLOYEE_PASSWORD")
        missing = [
            name
            for name, value in (
                ("MEMORY_PALACE_UAT_BASE_URL", base_url),
                ("ADMIN_USERNAME", admin_username),
                ("ADMIN_PASSWORD", admin_password),
                ("UAT_EMPLOYEE_PASSWORD", employee_password),
            )
            if not value
        ]
        if missing:
            raise UATBootstrapError(f"缺少 UAT 初始化配置：{', '.join(missing)}")
        if len(admin_password) < 8:
            raise UATBootstrapError("ADMIN_PASSWORD 长度不能少于 8 位")
        if len(employee_password) < 12:
            raise UATBootstrapError("UAT_EMPLOYEE_PASSWORD 长度不能少于 12 位")
        return cls(
            base_url=base_url.rstrip("/"),
            admin_username=admin_username,
            admin_password=admin_password,
            employee_password=employee_password,
        )


@dataclass(frozen=True)
class UATBootstrapResult:
    organization_name: str
    venue_id: str
    venue_name: str
    user_count: int
    identity_count: int
    sop_title: str
    sop_version: str
    expert_name: str
    baseline_snapshot: dict[str, Any]


@dataclass(frozen=True)
class _UATUserSpec:
    username: str
    display_name: str
    role: str
    department: str
    job_title: str

    @property
    def external_user_id(self) -> str:
        return f"wecom-{self.username}"


def _uat_user_specs(admin_username: str) -> tuple[_UATUserSpec, ...]:
    return (
        _UATUserSpec(admin_username, "刘海", "admin", "信息技术部", "系统管理员"),
        _UATUserSpec("li-ming", "李明", "operator", "东门运营组", "东门运营员"),
        _UATUserSpec("chen-yu", "陈雨", "operator", "设备保障部", "设备检修员"),
        _UATUserSpec("wang-fang", "王芳", "manager", "运营管理部", "当日值班经理"),
        _UATUserSpec("zhang-jianguo", "张建国", "operator", "设备保障部", "资深设备主管"),
        _UATUserSpec("zhao-min", "赵敏", "manager", "知识运营部", "知识负责人"),
        _UATUserSpec("zhou-qi", "周琪", "operator", "早班运营组", "早班运营员"),
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
        raise UATBootstrapError(f"无法读取 {name}_FILE 指向的密钥文件") from exc


class _FormalAPI:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client
        self.access_token = ""

    async def login(self, username: str, password: str) -> dict[str, Any]:
        payload = await self.request(
            "POST",
            "/api/v1/auth/login",
            body={"username": username, "password": password},
            authenticated=False,
        )
        token = payload.get("access_token")
        user = payload.get("user")
        if not isinstance(token, str) or not token or not isinstance(user, dict):
            raise UATBootstrapError("登录接口未返回有效访问令牌和管理员身份")
        self.access_token = token
        return user

    async def request(
        self,
        method: str,
        path: str,
        *,
        body: Optional[dict[str, Any]] = None,
        authenticated: bool = True,
    ) -> Any:
        headers = {"Accept": "application/json"}
        if authenticated:
            if not self.access_token:
                raise UATBootstrapError("尚未建立管理员会话")
            headers["Authorization"] = f"Bearer {self.access_token}"
        try:
            response = await self.client.request(method, path, json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise UATBootstrapError(f"正式 API 请求失败：{method} {path}") from exc
        if response.status_code < 200 or response.status_code >= 300:
            message = _response_error_message(response)
            raise UATBootstrapError(
                f"正式 API 拒绝初始化操作：{method} {path} -> {response.status_code}，{message}"
            )
        if response.status_code == 204 or not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise UATBootstrapError(f"正式 API 返回了无法解析的响应：{method} {path}") from exc


def _response_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return "响应不是 JSON"
    detail = payload.get("detail") if isinstance(payload, dict) else payload
    if isinstance(detail, dict):
        return str(detail.get("message") or detail.get("code") or "请求失败")
    if isinstance(detail, str):
        return detail
    return "请求失败"


async def bootstrap_uat_master_data(
    config: UATBootstrapConfig,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> UATBootstrapResult:
    """Initialize the frozen UAT baseline without writing databases directly."""
    owns_client = client is None
    active_client = client or httpx.AsyncClient(
        base_url=config.base_url.rstrip("/"),
        timeout=config.timeout_seconds,
        follow_redirects=True,
    )
    api = _FormalAPI(active_client)
    try:
        principal = await api.login(config.admin_username, config.admin_password)
        venues = await _list_venues(api)
        if any(venue.get("id") == UAT_VENUE_ID for venue in venues):
            await _assert_pristine_baseline(
                await _capture_pristine_state(api, venue_id=UAT_VENUE_ID)
            )
        await _ensure_venue(api, venues=venues)
        users = await _list_users(api)
        admin = _find_user(users, principal.get("id"), config.admin_username)
        admin_spec = _uat_user_specs(config.admin_username)[0]
        await _ensure_existing_user(api, admin, admin_spec)

        principal = await api.login(config.admin_username, config.admin_password)
        if principal.get("venue_id") != UAT_VENUE_ID or principal.get("role") != "admin":
            raise UATBootstrapError("UAT 管理员未进入悦山景区或不再具有管理员角色")

        await api.request(
            "PUT",
            "/api/v1/admin/settings/organization_name",
            body={"value": UAT_ORGANIZATION_NAME},
        )

        users_by_username = {user["username"].lower(): user for user in await _list_users(api)}
        ensured_users: dict[str, dict[str, Any]] = {}
        for spec in _uat_user_specs(config.admin_username):
            existing = users_by_username.get(spec.username.lower())
            if existing is None:
                user = await _create_user(api, spec, config.employee_password)
            else:
                user = await _ensure_existing_user(api, existing, spec)
                if spec.role != "admin":
                    await api.request(
                        "POST",
                        f"/api/v1/admin/users/{user['id']}/reset-password",
                        body={"password": config.employee_password},
                    )
            ensured_users[spec.username] = user

        identity_count = 0
        for spec in _uat_user_specs(config.admin_username):
            await api.request(
                "POST",
                "/api/v1/channels/identities",
                body={
                    "channel": "WECOM_SIMULATOR",
                    "external_tenant_id": UAT_EXTERNAL_TENANT_ID,
                    "external_user_id": spec.external_user_id,
                    "user_id": ensured_users[spec.username]["id"],
                    "status": "ACTIVE",
                },
            )
            identity_count += 1

        sop = await _ensure_published_sop(api)
        expert = await _ensure_signed_expert(api, ensured_users["zhang-jianguo"])
        await _verify_simulator_identities(api, _uat_user_specs(config.admin_username))
        baseline_snapshot = await _capture_baseline(api)
        _validate_ready_baseline(
            baseline_snapshot,
            specs=_uat_user_specs(config.admin_username),
        )
        return UATBootstrapResult(
            organization_name=UAT_ORGANIZATION_NAME,
            venue_id=UAT_VENUE_ID,
            venue_name=UAT_VENUE_NAME,
            user_count=len(ensured_users),
            identity_count=identity_count,
            sop_title=sop["title"],
            sop_version=sop["version"],
            expert_name=expert["display_name"],
            baseline_snapshot=baseline_snapshot,
        )
    finally:
        if owns_client:
            await active_client.aclose()


async def _list_venues(api: _FormalAPI) -> list[dict[str, Any]]:
    payload = await api.request("GET", "/api/v1/admin/venues")
    venues = payload.get("venues")
    if not isinstance(venues, list):
        raise UATBootstrapError("场地列表接口返回格式不正确")
    return venues


async def _ensure_venue(
    api: _FormalAPI,
    *,
    venues: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    venues = await _list_venues(api) if venues is None else venues
    venue = next((item for item in venues if item.get("id") == UAT_VENUE_ID), None)
    if venue is None:
        created = await api.request(
            "POST",
            "/api/v1/admin/venues",
            body={"id": UAT_VENUE_ID, "name": UAT_VENUE_NAME},
        )
        return created["venue"]
    changes = {}
    if venue.get("name") != UAT_VENUE_NAME:
        changes["name"] = UAT_VENUE_NAME
    if venue.get("status") != "ACTIVE":
        changes["status"] = "ACTIVE"
    if changes:
        updated = await api.request(
            "PATCH",
            f"/api/v1/admin/venues/{UAT_VENUE_ID}",
            body=changes,
        )
        return updated["venue"]
    return venue


async def _list_users(api: _FormalAPI) -> list[dict[str, Any]]:
    payload = await api.request("GET", "/api/v1/admin/users")
    users = payload.get("users")
    if not isinstance(users, list):
        raise UATBootstrapError("用户列表接口返回格式不正确")
    return users


def _find_user(users: list[dict[str, Any]], user_id: Any, username: str) -> dict[str, Any]:
    user = next((item for item in users if item.get("id") == user_id), None)
    if user is None:
        user = next((item for item in users if item.get("username", "").lower() == username.lower()), None)
    if user is None:
        raise UATBootstrapError("无法在正式用户列表中找到当前 UAT 管理员")
    return user


def _desired_user(spec: _UATUserSpec) -> dict[str, Any]:
    return {
        "display_name": spec.display_name,
        "role": spec.role,
        "venue_id": UAT_VENUE_ID,
        "department": spec.department,
        "job_title": spec.job_title,
        "status": "ACTIVE",
    }


async def _ensure_existing_user(
    api: _FormalAPI,
    user: dict[str, Any],
    spec: _UATUserSpec,
) -> dict[str, Any]:
    desired = _desired_user(spec)
    changes = {key: value for key, value in desired.items() if user.get(key) != value}
    if not changes:
        return user
    payload = await api.request(
        "PATCH",
        f"/api/v1/admin/users/{user['id']}",
        body=changes,
    )
    return payload["user"]


async def _create_user(api: _FormalAPI, spec: _UATUserSpec, password: str) -> dict[str, Any]:
    desired = _desired_user(spec)
    desired.pop("status")
    payload = await api.request(
        "POST",
        "/api/v1/admin/users",
        body={
            "username": spec.username,
            "password": password,
            **desired,
        },
    )
    return payload["user"]


async def _capture_baseline(
    api: _FormalAPI,
) -> dict[str, Any]:
    snapshot = await api.request("GET", "/api/v1/admin/uat-baseline")
    if not isinstance(snapshot, dict):
        raise UATBootstrapError("UAT 基线接口返回格式不正确")
    return snapshot


async def _capture_pristine_state(
    api: _FormalAPI,
    *,
    venue_id: str,
) -> dict[str, Any]:
    snapshot = await api.request("GET", f"/api/v1/admin/uat-pristine/{venue_id}")
    if not isinstance(snapshot, dict) or snapshot.get("venue_id") != venue_id:
        raise UATBootstrapError("UAT 场地前检接口返回格式不正确")
    return snapshot


async def _assert_pristine_baseline(snapshot: dict[str, Any]) -> None:
    counts = snapshot.get("process_counts")
    if not isinstance(counts, dict):
        raise UATBootstrapError("UAT 基线缺少业务过程计数")
    populated = {
        str(name): int(value)
        for name, value in counts.items()
        if isinstance(value, int) and value > 0
    }
    if populated:
        detail = "、".join(f"{name} {count} 条" for name, count in sorted(populated.items()))
        raise UATBootstrapError(
            "悦山景区已经存在演示旅程过程数据，初始化不会删除业务记录：" + detail
        )


def _validate_ready_baseline(
    snapshot: dict[str, Any],
    *,
    specs: tuple[_UATUserSpec, ...],
) -> None:
    channel = snapshot.get("channel")
    if channel != {
        "mode": "WECOM_SIMULATOR_ONLY",
        "identity_channel": "WECOM_SIMULATOR",
        "real_wecom_enabled": False,
    }:
        raise UATBootstrapError("UAT 基线渠道不是仅企微模拟器模式")
    scope = snapshot.get("scope")
    venue = scope.get("venue") if isinstance(scope, dict) else None
    if (
        not isinstance(scope, dict)
        or scope.get("organization_name") != UAT_ORGANIZATION_NAME
        or not isinstance(venue, dict)
        or venue.get("id") != UAT_VENUE_ID
        or venue.get("name") != UAT_VENUE_NAME
        or venue.get("status") != "ACTIVE"
    ):
        raise UATBootstrapError("UAT 基线的组织或场地主数据不完整")

    master_data = snapshot.get("master_data")
    if not isinstance(master_data, dict):
        raise UATBootstrapError("UAT 基线缺少主数据快照")
    users = master_data.get("users")
    identities = master_data.get("simulator_identities")
    sops = master_data.get("published_sops")
    experts = master_data.get("signed_experts")
    rules = master_data.get("approval_rules")
    expected_usernames = {spec.username for spec in specs}
    if not isinstance(users, list) or {item.get("username") for item in users} != expected_usernames:
        raise UATBootstrapError("UAT 基线必须且只能包含冻结的 7 名演示角色")
    if (
        not isinstance(identities, list)
        or len(identities) != len(specs)
        or any(item.get("channel") != "WECOM_SIMULATOR" for item in identities)
        or {item.get("user_id") for item in identities} != {item.get("id") for item in users}
    ):
        raise UATBootstrapError("UAT 基线的企微模拟器身份映射不完整")
    if not isinstance(sops, list) or not any(
        item.get("title") == UAT_SOP_TITLE
        and str(item.get("version")) == UAT_SOP_VERSION
        and item.get("status") == "PUBLISHED"
        for item in sops
    ):
        raise UATBootstrapError("UAT 基线缺少已发布的 2.1 版观光车 SOP")
    if not isinstance(experts, list) or not any(
        item.get("display_name") == "张建国" and item.get("authorization_status") == "SIGNED"
        for item in experts
    ):
        raise UATBootstrapError("UAT 基线缺少张建国的已签署专家授权")
    required_rules = {
        "SUSPEND_PASSENGER_VEHICLE",
        "ACTIVATE_BACKUP_VEHICLE",
        "SEND_CRITICAL_DISPATCH_ALERT",
    }
    if not isinstance(rules, list) or {item.get("code") for item in rules} != required_rules:
        raise UATBootstrapError("UAT 基线的高风险审批规则不完整")
    counts = snapshot.get("process_counts")
    if not isinstance(counts, dict) or not counts or any(value != 0 for value in counts.values()):
        raise UATBootstrapError("UAT 基线仍包含业务过程数据")


async def _ensure_published_sop(api: _FormalAPI) -> dict[str, Any]:
    payload = await api.request("GET", "/api/v1/admin/sops")
    sops = payload.get("sops", [])
    candidates = [
        item
        for item in sops
        if item.get("title") == UAT_SOP_TITLE and str(item.get("version")) == UAT_SOP_VERSION
    ]
    if candidates:
        sop = next((item for item in candidates if item.get("status") == "PUBLISHED"), candidates[0])
        if sop.get("content") != UAT_SOP_CONTENT:
            raise UATBootstrapError("现有 2.1 版 UAT SOP 内容与冻结演示基线不一致")
    else:
        created = await api.request(
            "POST",
            "/api/v1/admin/sops",
            body={
                "title": UAT_SOP_TITLE,
                "content": UAT_SOP_CONTENT,
                "category": "设备运营",
                "priority": 1,
                "version": UAT_SOP_VERSION,
            },
        )
        sop = created["sop"]

    if sop.get("status") in {"DRAFT", "REJECTED"}:
        submitted = await api.request("POST", f"/api/v1/admin/sops/{sop['id']}/submit")
        sop = submitted["sop"]
    if sop.get("status") == "IN_REVIEW":
        published = await api.request(
            "POST",
            f"/api/v1/admin/sops/{sop['id']}/publish",
            body={"comment": "UAT 基线 SOP 已核验并发布"},
        )
        sop = published["sop"]
    if sop.get("status") != "PUBLISHED":
        raise UATBootstrapError(f"UAT SOP 无法进入已发布状态，当前状态：{sop.get('status')}")
    return sop


async def _ensure_signed_expert(api: _FormalAPI, user: dict[str, Any]) -> dict[str, Any]:
    desired = {
        "display_name": "张建国",
        "job_title": "资深设备主管",
        "department": "设备保障部",
        "years_experience": 18,
        "expertise": ["观光车检修", "雨后复运", "轮端异响判断"],
        "authorization_status": "SIGNED",
        "authorization_statement": UAT_EXPERT_AUTHORIZATION_STATEMENT,
    }
    payload = await api.request("GET", "/api/v1/admin/experts")
    experts = payload.get("experts", [])
    expert = next((item for item in experts if item.get("user_id") == user["id"]), None)
    if expert is None:
        created = await api.request(
            "POST",
            "/api/v1/admin/experts",
            body={"user_id": user["id"], **desired},
        )
        return created["expert"]
    changes = {key: value for key, value in desired.items() if expert.get(key) != value}
    if changes:
        updated = await api.request(
            "PATCH",
            f"/api/v1/admin/experts/{expert['id']}",
            body=changes,
        )
        return updated["expert"]
    return expert


async def _verify_simulator_identities(api: _FormalAPI, specs: tuple[_UATUserSpec, ...]) -> None:
    payload = await api.request("GET", "/api/v1/channels/simulator-identities")
    identities = payload.get("identities", [])
    visible_specs = {spec.username: spec for spec in specs if spec.role in {"manager", "operator"}}
    visible = {item.get("username"): item for item in identities}
    missing = sorted(set(visible_specs) - set(visible))
    if missing:
        raise UATBootstrapError("企微模拟器缺少已授权员工身份：" + "、".join(missing))
    for username, spec in visible_specs.items():
        identity = visible[username]
        if (
            identity.get("organization_name") != UAT_ORGANIZATION_NAME
            or identity.get("venue_name") != UAT_VENUE_NAME
            or identity.get("department") != spec.department
            or identity.get("job_title") != spec.job_title
            or identity.get("wecom_binding_status") != "ACTIVE"
        ):
            raise UATBootstrapError(f"企微模拟身份 {spec.display_name} 的企业主数据不完整")
