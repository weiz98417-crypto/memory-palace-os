"""Machine-readable unified employee-assistant MVP registry and release gate."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


REGISTRY_PATH = Path(__file__).with_name("feature_registry.yaml")
ALLOWED_STATUSES = {
    "READY",
    "DISABLED_REQUIRES_CONFIG",
    "DISABLED_BY_POLICY",
    "BLOCKED",
    "NOT_IN_MVP",
}
REQUIRED_ITEM_FIELDS = {
    "id",
    "name",
    "category",
    "owner",
    "status",
    "interactive",
    "entrypoints",
    "roles",
    "tenant_scope",
    "apis",
    "services",
    "agents",
    "permission",
    "data_dependencies",
    "audit_events",
    "trace_query",
    "error_codes",
    "tests",
    "evidence",
    "backup_restore",
    "external_config",
    "known_limitations",
    "blocked_reason",
    "references",
}
TEST_KINDS = {"unit", "integration", "browser", "live", "uat"}
EVIDENCE_KINDS = {"automated", "browser", "live", "uat"}
REFERENCE_KINDS = {"code", "openspec", "docs", "release"}
Requirement = tuple[str, str, str]
DELIVERY_EVIDENCE_REQUIREMENTS: tuple[Requirement, ...] = (
    ("delivery", "browser", "浏览器验收证据"),
    ("delivery", "live", "Live 验收证据"),
    ("delivery", "uat", "UAT 验收证据"),
)
EXPECTED_BUSINESS_IDS = {f"MVP-BIZ-{number:03d}" for number in range(1, 21)}
EXPECTED_AGENT_IDS = {
    "ContextTrigger",
    "Router",
    "Commander",
    "MemoryOps",
    "Persona",
    "PersonaExtract",
    "TodoWrite",
    "Watcher",
}
EXPECTED_UAT_IDS = {
    *(f"E2E-{number:02d}" for number in range(17)),
    *(f"UAT-F{number:02d}" for number in range(1, 14)),
}
EXPECTED_BASELINE_DOCUMENTS = [
    "PRD-memory-palace-unified-agent-experience-mvp.md",
    "docs/product/unified-agent-page-map.md",
    "docs/product/unified-agent-demo-journey.md",
]
LEGACY_DELIVERY_EVIDENCE_PREFIX = "docs/verification/mvp-uat-20260728/"
REQUIRED_UAT_FIELDS = {"id", "name", "covers", "status", "evidence"}
UAT_STATUSES = {"READY", "BLOCKED"}

FEATURE_REQUIREMENTS: dict[str, tuple[Requirement, ...]] = {
    "MVP-BIZ-001": (
        ("audit", "AUTH_LOGIN", "成功登录审计"),
        ("audit", "AUTH_REFRESH", "令牌刷新审计"),
        ("audit", "AUTH_LOGOUT", "安全退出审计"),
    ),
    "MVP-BIZ-002": (
        ("runtime", "database", "数据库健康"),
        ("runtime", "queue", "消息队列健康"),
        ("fact", "events.total", "大屏存在真实事件数据"),
        ("fact", "tasks.total", "大屏存在真实任务数据"),
    ),
    "MVP-BIZ-003": (
        ("message_agent_chain", "MVP-BIZ-003", "同 Trace 消息 Agent 链"),
    ),
    "MVP-BIZ-004": (
        ("fact", "events.total", "历史事件已持久化"),
        ("audit", "EVENT_CREATED", "事件补录成功审计"),
        ("runtime", "chromadb", "向量库健康"),
    ),
    "MVP-BIZ-005": (
        ("fact", "events.total", "事件列表与详情存在真实数据"),
        ("audit", "EVENT_CREATED", "事件来源审计"),
    ),
    "MVP-BIZ-006": (
        ("fact", "events.closed", "事件已完成闭环"),
        ("audit", "EVENT_UPDATED", "事件处置更新审计"),
        ("audit", "EVENT_CLOSE_DENIED", "闭环门禁拒绝审计"),
        ("audit", "EVENT_CLOSED", "事件闭环审计"),
        ("audit", "EXPERIENCE_CANDIDATE_CREATED", "闭环经验候选创建审计"),
    ),
    "MVP-BIZ-007": (
        ("fact", "message_runs.total", "消息运行记录已持久化"),
        ("fact", "sessions.total", "会话记录已持久化"),
        ("fact", "sessions.closed", "会话已完成关闭"),
        ("audit", "SESSION_CLOSED", "会话关闭审计"),
    ),
    "MVP-BIZ-008": (
        ("fact", "tasks.done", "任务已执行完成"),
        ("audit", "TASK_CREATED", "任务创建审计"),
        ("audit", "TASK_ASSIGNED", "任务分配审计"),
        ("audit", "TASK_STARTED", "任务启动审计"),
        ("audit", "TASK_FAILED", "任务失败审计"),
        ("audit", "TASK_RETRIED", "任务恢复审计"),
        ("audit", "TASK_COMPLETED", "任务完成审计"),
    ),
    "MVP-BIZ-009": (
        ("fact", "approvals.approved", "审批批准记录"),
        ("fact", "approvals.rejected", "审批拒绝记录"),
        ("fact", "approvals.executed", "批准后的真实执行结果"),
        ("audit", "CONTROLLED_ACTION_REQUESTED", "受控动作申请审计"),
        ("audit", "APPROVAL_APPROVED", "审批批准审计"),
        ("audit", "APPROVAL_REJECTED", "审批拒绝审计"),
    ),
    "MVP-BIZ-010": (
        ("fact", "push_logs.total", "推送记录已持久化"),
        ("fact", "push_logs.reviewed", "推送采纳结果已确认"),
        ("fact", "tool_invocations.total", "受控工具调用日志"),
        ("audit", "PUSH_ADOPTION_UPDATED", "推送采纳审计"),
    ),
    "MVP-BIZ-011": (
        ("fact", "knowledge.total", "知识条目已持久化"),
        ("audit", "KNOWLEDGE_CREATED", "知识创建审计"),
        ("audit", "KNOWLEDGE_UPDATED", "知识编辑审计"),
        ("runtime", "chromadb", "语义检索向量库健康"),
    ),
    "MVP-BIZ-012": (
        ("fact", "knowledge.total", "知识资产已持久化"),
        ("audit", "KNOWLEDGE_CREATED", "知识创建审计"),
        ("audit", "KNOWLEDGE_UPDATED", "知识编辑审计"),
        ("audit", "KNOWLEDGE_INDEX_REBUILT", "知识索引重建审计"),
    ),
    "MVP-BIZ-013": (
        ("fact", "sops.published", "SOP 已发布"),
        ("audit", "SOP_CREATED", "SOP 创建审计"),
        ("audit", "SOP_SUBMITTED", "SOP 提审审计"),
        ("audit", "SOP_REJECTED", "SOP 驳回审计"),
        ("audit", "SOP_UPDATED", "SOP 修订审计"),
        ("audit", "SOP_PUBLISHED", "SOP 发布审计"),
    ),
    "MVP-BIZ-014": (
        ("fact", "expert_profiles.total", "专家档案已持久化"),
        ("audit", "EXPERT_CREATED", "专家档案创建审计"),
        ("audit", "EXPERT_AUTHORIZATION_SIGNED", "专家经验授权签署审计"),
    ),
    "MVP-BIZ-015": (
        ("fact", "experience_interviews.completed", "统一助手专家访谈已完成"),
        ("fact", "experience_cards.draft", "PersonaExtract 已生成待审核经验草稿"),
        ("audit", "EXPERIENCE_INTERVIEW_INVITED", "专家访谈邀请审计"),
        ("audit", "EXPERIENCE_DRAFT_CREATED", "经验草稿创建审计"),
    ),
    "MVP-BIZ-016": (
        ("fact", "experience_cards.published", "经验卡已审核发布并建立索引"),
        ("fact", "experience_usage_logs.referenced", "统一助手已真实引用授权经验"),
        ("integration", "deepseek.live_verified", "DeepSeek 非 Mock 成功调用"),
        ("audit", "EXPERIENCE_PUBLISHED", "经验发布审计"),
    ),
    "MVP-BIZ-017": (
        ("fact", "watcher_policies.total", "Watcher 策略已持久化"),
        ("fact", "watcher_runs.succeeded", "Watcher 策略运行成功"),
        ("audit", "WATCHER_POLICY_CREATED", "Watcher 策略创建审计"),
        ("audit", "WATCHER_POLICY_UPDATED", "Watcher 策略更新审计"),
        ("audit", "WATCHER_RUN", "Watcher 手动运行审计"),
        ("runtime", "scheduler", "调度器健康"),
    ),
    "MVP-BIZ-018": (
        ("fact", "watcher_runs.succeeded", "Watcher 巡检运行成功"),
        ("fact", "watcher_findings.assigned", "巡检发现已分配"),
        ("fact", "watcher_findings.closed", "巡检发现已关闭"),
        ("audit", "WATCHER_RUN", "Watcher 运行审计"),
        ("audit", "EVENT_WATCHER_CHECK", "事件级 Watcher 检查审计"),
        ("audit", "WATCHER_FINDING_UPDATED", "巡检发现分配审计"),
        ("audit", "WATCHER_FINDING_CLOSED", "巡检发现关闭审计"),
    ),
    "MVP-BIZ-019": (
        ("fact", "users.total", "场地用户已持久化"),
        ("fact", "venues.total", "多场地已持久化"),
        ("audit", "USER_CREATED", "用户创建审计"),
        ("audit", "USER_UPDATED", "用户停启用审计"),
        ("audit", "USER_PASSWORD_RESET", "密码重置审计"),
        ("audit", "VENUE_CREATED", "场地创建审计"),
    ),
    "MVP-BIZ-020": (
        ("fact", "settings.total", "系统设置已持久化"),
        ("audit", "SETTING_UPDATED", "系统设置更新审计"),
        ("audit", "CONFIG_RELOADED", "运行时配置重载审计"),
        ("audit", "SKILL_RELOADED", "Agent 热重载审计"),
    ),
    "MVP-INTEGRATION-DEEPSEEK": (
        ("integration", "deepseek.live_verified", "DeepSeek v4 Flash 非 Mock 成功调用"),
        ("fact", "llm_calls.event_dossier_visible", "DeepSeek 调用已同步进入事件卷宗"),
    ),
    "MVP-INTEGRATION-WECHAT": (
        ("integration", "wechat.safe_disabled_verified", "真实企业微信按项目策略安全禁用"),
    ),
    "MVP-INTEGRATION-SMS": (
        ("integration", "sms.live_verified", "短信供应商沙箱发送成功证据"),
    ),
    "MVP-INTEGRATION-VOICE": (
        ("integration", "voice.live_verified", "语音供应商沙箱呼叫成功证据"),
    ),
    "MVP-PLATFORM-AUTHZ": (
        ("fact", "users.total", "租户用户已持久化"),
        ("audit", "AUTH_LOGIN", "认证成功审计"),
        ("audit", "SESSION_CLOSE_DENIED", "跨租户访问拒绝审计"),
    ),
    "MVP-PLATFORM-POSTGRES": (
        ("runtime", "database", "PostgreSQL 健康"),
        ("fact", "backups.completed", "备份恢复记录已完成"),
    ),
    "MVP-PLATFORM-REDIS": (
        ("runtime", "queue", "Redis Streams 健康"),
        ("audit", "DEAD_LETTER_RETRIED", "死信恢复审计"),
    ),
    "MVP-PLATFORM-CHROMA": (
        ("runtime", "chromadb", "ChromaDB 健康"),
        ("fact", "knowledge.total", "向量知识资产已持久化"),
        ("audit", "KNOWLEDGE_INDEX_REBUILT", "索引重建审计"),
    ),
    "MVP-PLATFORM-HEALTH": (
        ("runtime", "database", "数据库健康"),
        ("runtime", "queue", "消息队列健康"),
        ("runtime", "chromadb", "向量库健康"),
        ("runtime", "scheduler", "调度器健康"),
        ("fact", "runtime_recovery_runs.succeeded", "App 启动恢复结果已持久化"),
        ("audit", "CONFIG_RELOADED", "配置重载审计"),
        ("audit", "SKILL_RELOADED", "Agent 热重载审计"),
    ),
}

for _agent_id in EXPECTED_AGENT_IDS:
    FEATURE_REQUIREMENTS[_agent_id] = (
        ("integration", "deepseek.live_verified", "DeepSeek 非 Mock 成功调用"),
        ("agent_trace", _agent_id, f"{_agent_id} 归属明确的成功 Trace"),
    )

INTEGRATION_ITEM_IDS = {
    "MVP-INTEGRATION-DEEPSEEK": "deepseek",
    "MVP-INTEGRATION-WECHAT": "wechat",
    "MVP-INTEGRATION-SMS": "sms",
    "MVP-INTEGRATION-VOICE": "voice",
}
OPTIONAL_EXTERNAL_INTEGRATION_IDS = {
    "MVP-INTEGRATION-WECHAT",
    "MVP-INTEGRATION-SMS",
    "MVP-INTEGRATION-VOICE",
}


class FeatureRegistryError(ValueError):
    pass


def _require_keys(value: Any, required: set[str], label: str) -> None:
    if not isinstance(value, dict):
        raise FeatureRegistryError(f"{label} must be an object")
    missing = sorted(required - set(value))
    if missing:
        raise FeatureRegistryError(f"{label} missing fields: {', '.join(missing)}")


def _validate_ready(item: dict[str, Any]) -> None:
    item_id = item["id"]
    required_lists = {
        "entrypoints": item["entrypoints"],
        "roles": item["roles"],
        "apis": item["apis"],
        "services": item["services"],
        "data_dependencies": item["data_dependencies"],
        "audit_events": item["audit_events"],
        "error_codes": item["error_codes"],
    }
    empty = [name for name, values in required_lists.items() if not values]
    evidence_empty = [name for name in EVIDENCE_KINDS if not item["evidence"].get(name)]
    reference_empty = [name for name in REFERENCE_KINDS if not item["references"].get(name)]
    if not item["interactive"] or empty or evidence_empty or reference_empty or not item["trace_query"]:
        details = empty + evidence_empty + reference_empty
        raise FeatureRegistryError(
            f"READY item {item_id} lacks complete delivery evidence: {', '.join(details) or 'interactive/trace'}"
        )


def validate_feature_registry(registry: dict[str, Any], *, enforce_prd_scope: bool = False) -> dict[str, Any]:
    if not isinstance(registry, dict) or not isinstance(registry.get("items"), list):
        raise FeatureRegistryError("feature registry must contain an items list")
    if not isinstance(registry.get("uat_journeys"), list):
        raise FeatureRegistryError("feature registry must contain a uat_journeys list")

    seen_ids: set[str] = set()
    for index, item in enumerate(registry["items"]):
        label = f"items[{index}]"
        _require_keys(item, REQUIRED_ITEM_FIELDS, label)
        item_id = str(item["id"])
        if item_id in seen_ids:
            raise FeatureRegistryError(f"duplicate feature id: {item_id}")
        seen_ids.add(item_id)
        if item["status"] not in ALLOWED_STATUSES:
            raise FeatureRegistryError(f"{item_id} has invalid status {item['status']}")
        _require_keys(item["tests"], TEST_KINDS, f"{item_id}.tests")
        _require_keys(item["evidence"], EVIDENCE_KINDS, f"{item_id}.evidence")
        _require_keys(item["references"], REFERENCE_KINDS, f"{item_id}.references")
        if item["status"] == "READY":
            _validate_ready(item)
        elif item["status"] == "DISABLED_REQUIRES_CONFIG":
            if item["interactive"] or not item["external_config"] or not item["blocked_reason"]:
                raise FeatureRegistryError(
                    f"DISABLED_REQUIRES_CONFIG item {item_id} must be non-interactive and name missing config"
                )
        elif item["status"] == "DISABLED_BY_POLICY":
            if item["interactive"] or not item["blocked_reason"]:
                raise FeatureRegistryError(
                    f"DISABLED_BY_POLICY item {item_id} must be non-interactive and explain the policy"
                )
        elif item["status"] == "BLOCKED" and not item["blocked_reason"]:
            raise FeatureRegistryError(f"BLOCKED item {item_id} must include blocked_reason")

    seen_journey_ids: set[str] = set()
    for index, journey in enumerate(registry["uat_journeys"]):
        label = f"uat_journeys[{index}]"
        _require_keys(journey, REQUIRED_UAT_FIELDS, label)
        journey_id = str(journey["id"])
        if journey_id in seen_journey_ids:
            raise FeatureRegistryError(f"duplicate UAT journey id: {journey_id}")
        seen_journey_ids.add(journey_id)
        if journey["status"] not in UAT_STATUSES:
            raise FeatureRegistryError(f"{journey['id']} has invalid UAT status {journey['status']}")
        if not isinstance(journey["covers"], list) or not journey["covers"]:
            raise FeatureRegistryError(f"{journey['id']} must cover at least one registry item")
        if not isinstance(journey["evidence"], list) or any(
            not isinstance(reference, str) or not reference.strip()
            for reference in journey["evidence"]
        ):
            raise FeatureRegistryError(f"{journey['id']} evidence must be a list of non-empty references")
        if journey["status"] == "READY" and not journey["evidence"]:
            raise FeatureRegistryError(f"READY journey {journey['id']} requires acceptance evidence")
        unknown_covers = sorted(set(journey["covers"]) - seen_ids)
        if unknown_covers:
            raise FeatureRegistryError(
                f"{journey_id} covers unknown registry items: {', '.join(unknown_covers)}"
            )

    if enforce_prd_scope:
        if registry.get("baseline") != EXPECTED_BASELINE_DOCUMENTS[0]:
            raise FeatureRegistryError("registry baseline must be the unified employee-assistant MVP PRD")
        if registry.get("baseline_documents") != EXPECTED_BASELINE_DOCUMENTS:
            raise FeatureRegistryError("registry must reference the PRD, page map and demo journey")
        business_ids = {item["id"] for item in registry["items"] if item["category"] == "business"}
        agent_ids = {item["id"] for item in registry["items"] if item["category"] == "agent"}
        uat_ids = {journey.get("id") for journey in registry["uat_journeys"]}
        if business_ids != EXPECTED_BUSINESS_IDS:
            raise FeatureRegistryError("registry must contain exactly MVP-BIZ-001 through MVP-BIZ-020")
        if agent_ids != EXPECTED_AGENT_IDS:
            raise FeatureRegistryError("registry must contain all eight required agents")
        if uat_ids != EXPECTED_UAT_IDS:
            raise FeatureRegistryError("registry must contain E2E-00..16 and UAT-F01..13")
        covered = {
            feature_id
            for journey in registry["uat_journeys"]
            for feature_id in journey.get("covers", [])
            if str(feature_id).startswith("MVP-BIZ-")
        }
        if covered != EXPECTED_BUSINESS_IDS:
            raise FeatureRegistryError("UAT journeys must cover all twenty business features")
    return registry


def load_feature_registry(path: Path | None = None) -> dict[str, Any]:
    registry_path = path or REGISTRY_PATH
    with registry_path.open("r", encoding="utf-8") as handle:
        registry = yaml.safe_load(handle)
    return validate_feature_registry(registry, enforce_prd_scope=True)


def _record_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [record for record in value if isinstance(record, dict)]
    return []


def _successful_record(record: dict[str, Any]) -> bool:
    return record.get("status") in {"COMPLETED", "SUCCEEDED"} or record.get("success") is True


def _live_deepseek_trace(evidence: dict[str, Any]) -> str | None:
    integration = evidence.get("integrations", {}).get("deepseek", {})
    live_call = integration.get("evidence") if integration.get("live_verified") else None
    if (
        not isinstance(live_call, dict)
        or not _successful_record(live_call)
        or live_call.get("is_mock") is not False
    ):
        return None
    return live_call.get("trace_id") or None


def _agent_success_rows(evidence: dict[str, Any], agent_id: str) -> list[dict[str, Any]]:
    value = evidence.get("facts", {}).get(f"agents.{agent_id}.live_succeeded")
    return [
        row
        for row in _record_list(value)
        if (row.get("agent_id") or row.get("agent_name")) == agent_id
        and row.get("trace_id")
        and _successful_record(row)
        and row.get("is_mock") is False
    ]


def _requirement_result(
    requirement: Requirement,
    evidence: dict[str, Any],
    item: dict[str, Any],
) -> tuple[bool, list[dict[str, Any]]]:
    kind, key, _label = requirement
    if kind == "delivery":
        records = item.get("evidence", {}).get(key, [])
        records = records if isinstance(records, list) else []
        records = [
            record
            for record in records
            if isinstance(record, str) and LEGACY_DELIVERY_EVIDENCE_PREFIX not in record
        ]
        return bool(records), [{"kind": "delivery", "key": key, "reference": record} for record in records]
    if kind == "agent_trace":
        matching_rows = _agent_success_rows(evidence, key)
        return bool(matching_rows), matching_rows[:1]
    if kind == "message_agent_chain":
        completed = evidence.get("facts", {}).get("message_runs.completed")
        completed_traces: set[str] = {
            str(row["trace_id"])
            for row in _record_list(completed)
            if row.get("trace_id") and _successful_record(row)
        }


        def agent_traces(agent_id: str) -> set[str]:
            return {str(row["trace_id"]) for row in _agent_success_rows(evidence, agent_id)}

        matching_traces = (
            completed_traces
            & agent_traces("ContextTrigger")
            & agent_traces("Router")
            & agent_traces("Commander")
            & agent_traces("MemoryOps")
        )
        if not matching_traces:
            return False, []
        trace_id = sorted(matching_traces)[0]
        return True, [
            {
                "kind": "message_agent_chain",
                "trace_id": trace_id,
                "agents": ["ContextTrigger", "Router", "Commander", "MemoryOps"],
            }
        ]
    if kind == "audit":
        audit_rows = evidence.get("audits", {}).get(key, [])
        if isinstance(audit_rows, dict):
            audit_rows = [audit_rows]
        return bool(audit_rows), list(audit_rows)
    if kind == "fact":
        value = evidence.get("facts", {}).get(key)
        return bool(value), ([{"kind": "fact", "key": key, "value": value}] if value else [])
    if kind == "runtime":
        value = evidence.get("runtime", {}).get(key)
        met = value == "healthy"
        return met, ([{"kind": "runtime", "key": key, "status": value}] if met else [])
    if kind == "integration":
        integration_id, attribute = key.split(".", 1)
        integration = evidence.get("integrations", {}).get(integration_id, {})
        met = bool(integration.get(attribute))
        record = integration.get("evidence") or {
            "kind": "integration",
            "key": key,
            "status": integration.get("status"),
        }
        return met, ([record] if met else [])
    return False, []


def _apply_runtime_evidence(registry: dict[str, Any], evidence: dict[str, Any]) -> None:
    for item in registry["items"]:
        item["declared_status"] = item["status"]
        requirements = FEATURE_REQUIREMENTS.get(
            item["id"],
            (("unsupported", item["id"], "尚未定义运行时验收规则"),),
        )
        if item["category"] in {"business", "agent"}:
            requirements += DELIVERY_EVIDENCE_REQUIREMENTS
        required = [requirement[2] for requirement in requirements]
        satisfied: list[str] = []
        runtime_evidence: list[dict[str, Any]] = []
        for requirement in requirements:
            met, records = _requirement_result(requirement, evidence, item)
            if met:
                satisfied.append(requirement[2])
                runtime_evidence.extend(records)
        missing = [label for label in required if label not in satisfied]
        item["acceptance"] = {
            "required": required,
            "satisfied": satisfied,
            "missing": missing,
        }
        item["runtime_evidence"] = runtime_evidence
        integration = evidence.get("integrations", {}).get(INTEGRATION_ITEM_IDS.get(item["id"], ""), {})
        policy_disabled = (
            item["id"] == "MVP-INTEGRATION-WECHAT"
            and integration.get("status") == "DISABLED_BY_POLICY"
            and integration.get("safe_disabled_verified") is True
        )
        if policy_disabled:
            item["safe_disabled_verified"] = True
            item["status"] = "DISABLED_BY_POLICY"
            item["blocked_reason"] = integration.get("blocked_reason") or (
                "本项目仅允许企微模拟器，真实企业微信收发已按项目策略禁用。"
            )
        elif not missing:
            item["status"] = "READY"
            item["blocked_reason"] = None
        elif item["id"] in INTEGRATION_ITEM_IDS:
            item["safe_disabled_verified"] = bool(integration.get("safe_disabled_verified"))
            if not integration.get("configured"):
                if item["safe_disabled_verified"]:
                    runtime_evidence.append(
                        {
                            "kind": "integration_safe_disabled",
                            "integration_id": INTEGRATION_ITEM_IDS[item["id"]],
                            "status": "DISABLED_REQUIRES_CONFIG",
                        }
                    )
                item["status"] = "DISABLED_REQUIRES_CONFIG"
                item["blocked_reason"] = integration.get("blocked_reason") or "缺少外部集成配置。"
            else:
                item["status"] = "BLOCKED"
                item["blocked_reason"] = integration.get("blocked_reason") or (
                    "缺少运行时验收证据：" + "；".join(missing)
                )
        else:
            item["status"] = "BLOCKED"
            item["blocked_reason"] = "缺少运行时验收证据：" + "；".join(missing)


def _apply_journey_evidence(registry: dict[str, Any]) -> None:
    items = {item["id"]: item for item in registry["items"]}
    for journey in registry["uat_journeys"]:
        journey["declared_status"] = journey["status"]
        declared_evidence = list(journey.get("evidence", []))
        required = [*journey.get("covers", []), "旅程验收证据"]
        def is_satisfied(item_id: str) -> bool:
            item = items.get(item_id, {})
            if item.get("status") == "READY":
                return True
            return (
                item_id in OPTIONAL_EXTERNAL_INTEGRATION_IDS
                and item.get("status") in {"DISABLED_REQUIRES_CONFIG", "DISABLED_BY_POLICY"}
                and item.get("safe_disabled_verified") is True
            )
        satisfied = [item_id for item_id in journey.get("covers", []) if is_satisfied(item_id)]
        if journey["declared_status"] == "READY" and declared_evidence:
            satisfied.append("旅程验收证据")
        missing = [item_id for item_id in required if item_id not in satisfied]
        journey["acceptance"] = {
            "required": required,
            "satisfied": satisfied,
            "missing": missing,
        }
        journey["evidence"] = declared_evidence + [
            evidence
            for item_id in satisfied
            if item_id in items
            for evidence in items[item_id].get("runtime_evidence", [])
        ]
        journey["status"] = "READY" if not missing else "BLOCKED"
        journey["blocked_reason"] = None if not missing else "覆盖项尚未 READY：" + "、".join(missing)




def _release_gate_passed(registry: dict[str, Any]) -> bool:
    def item_satisfied(item: dict[str, Any]) -> bool:
        if item.get("status") == "READY":
            return True
        return (
            item.get("id") in OPTIONAL_EXTERNAL_INTEGRATION_IDS
            and item.get("status") in {"DISABLED_REQUIRES_CONFIG", "DISABLED_BY_POLICY"}
            and item.get("safe_disabled_verified") is True
        )

    return all(item_satisfied(item) for item in registry["items"]) and all(
        journey.get("status") == "READY" for journey in registry["uat_journeys"]
    )
def registry_snapshot(
    path: Path | None = None,
    *,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    registry = deepcopy(load_feature_registry(path))
    _apply_runtime_evidence(registry, evidence or {})
    _apply_journey_evidence(registry)
    counts = Counter(item["status"] for item in registry["items"])
    visible = [item for item in registry["items"] if item["category"] == "business"]
    ready_visible = [item for item in visible if item["status"] == "READY"]
    registry["summary"] = {
        "total": len(registry["items"]),
        "by_status": dict(sorted(counts.items())),
        "business_total": len(visible),
        "business_ready": len(ready_visible),
        "visible_availability": len(ready_visible) / len(visible) if visible else 0.0,
        "release_gate_passed": _release_gate_passed(registry),
    }
    return registry
