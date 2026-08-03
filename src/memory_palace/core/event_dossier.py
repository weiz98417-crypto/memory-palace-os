import json
from typing import Any, Optional

from .attachments import message_attachments as load_message_attachments
from .event_closure import calculate_event_closure_conditions
from .sensitive_output import public_error_message, sanitize_public_value


EVENT_STATUS_LABELS = {
    "OPEN": "处理中",
    "CLOSED": "已闭环",
}

TASK_STATUS_LABELS = {
    "BLOCKED": "已阻塞",
    "PENDING": "待执行",
    "RUNNING": "执行中",
    "DONE": "已完成",
    "FAILED": "执行失败",
}

APPROVAL_STATUS_LABELS = {
    "PENDING": "待审批",
    "APPROVED": "已批准",
    "REJECTED": "已拒绝",
}

EXECUTION_STATUS_LABELS = {
    "NOT_STARTED": "尚未执行",
    "EXECUTING": "执行中",
    "EXECUTED": "已执行",
    "SUCCEEDED": "已执行",
    "FAILED": "执行失败，可重试",
}

ACTIVITY_LABELS = {
    "EVENT_CREATED": "事件已受理",
    "EVENT_UPDATED": "事件信息已更新",
    "TASK_CREATED": "处置任务已创建",
    "TASK_DECOMPOSED": "处置任务已拆解",
    "TASK_ASSIGNED": "任务负责人已更新",
    "TASK_STARTED": "任务已开始",
    "TASK_COMPLETED": "任务已完成",
    "TASK_FAILED": "任务执行失败",
    "TASK_RETRIED": "任务已恢复",
    "TASK_BLOCKED": "任务遇到现场阻碍",
    "TASK_UNBLOCKED": "任务阻碍已解除",
    "APPROVAL_REQUESTED": "受控动作待审批",
    "APPROVAL_REJECTED": "受控动作已拒绝",
    "APPROVAL_RESUBMITTED": "受控动作已重新提交",
    "APPROVAL_APPROVED": "受控动作已批准",
    "CONTROLLED_ACTION_EXECUTED": "受控动作已执行",
    "CONTROLLED_ACTION_FAILED": "受控动作执行失败",
    "WATCHER_COMPLETED": "闭环检查已完成",
    "EVENT_CLOSE_DENIED": "事件暂不具备闭环条件",
    "EVENT_CLOSED": "事件已闭环",
    "EXPERIENCE_CANDIDATE_CREATED": "已生成经验候选",
}

TOOL_LABELS = {
    "send_in_app_alert": "发送企业内通知",
    "send_wechat_message": "发送企微通知",
    "send_sms": "发送短信通知",
}


def _decode_json(value: Any, fallback: Any) -> Any:
    if value is None or value == "":
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _person(user: Optional[dict[str, Any]], empty_name: str) -> dict[str, Any]:
    if not user:
        return {
            "name": empty_name,
            "department": "暂无部门信息",
            "job_title": "暂无岗位信息",
            "role": None,
        }
    return {
        "name": user.get("display_name") or user.get("username") or empty_name,
        "department": user.get("department") or "暂无部门信息",
        "job_title": user.get("job_title") or "暂无岗位信息",
        "role": user.get("role"),
    }


def _task_result(value: Any) -> dict[str, Any]:
    decoded = _decode_json(value, None)
    if isinstance(decoded, dict):
        return {"kind": "fields", "fields": decoded}
    if isinstance(decoded, list):
        return {"kind": "items", "items": decoded}
    return {"kind": "text", "text": str(value or "尚未提交结果")}


def _activity_summary(activity_type: str, payload: dict[str, Any]) -> str:
    for key in (
        "summary",
        "description",
        "resolution",
        "comment",
        "message",
        "reason",
    ):
        if payload.get(key):
            return str(payload[key])
    return ACTIVITY_LABELS.get(activity_type, "业务状态已更新")


async def build_event_dossier(
    database,
    *,
    event: dict[str, Any],
    venue_id: str,
) -> dict[str, Any]:
    event_id = str(event["event_id"])
    activities = await database.fetch_all(
        """
        SELECT * FROM event_activities
        WHERE venue_id = ? AND event_id = ?
        ORDER BY created_at ASC, id ASC
        """,
        (venue_id, event_id),
    )
    tasks = await database.fetch_all(
        """
        SELECT * FROM tasks
        WHERE venue_id = ? AND event_id = ?
        ORDER BY created_at ASC, id ASC
        """,
        (venue_id, event_id),
    )
    approvals = await database.fetch_all(
        """
        SELECT * FROM approval_requests
        WHERE venue_id = ? AND event_id = ?
        ORDER BY requested_at ASC, approval_id ASC
        """,
        (venue_id, event_id),
    )
    watcher_run_rows = await database.fetch_all(
        """
        SELECT * FROM watcher_runs
        WHERE venue_id = ? AND event_id = ?
        ORDER BY started_at DESC, id DESC
        """,
        (venue_id, event_id),
    )
    experience_candidate_rows = await database.fetch_all(
        """
        SELECT * FROM experience_candidates
        WHERE venue_id = ? AND source_event_id = ?
        ORDER BY updated_at DESC, id DESC
        """,
        (venue_id, event_id),
    )
    experience_interview_rows = await database.fetch_all(
        """
        SELECT id, business_id, status, updated_at
        FROM experience_interviews
        WHERE venue_id = ? AND source_event_id = ?
        ORDER BY updated_at DESC, id DESC
        """,
        (venue_id, event_id),
    )
    closure_conditions = await calculate_event_closure_conditions(
        database,
        venue_id=venue_id,
        event_id=event_id,
        tasks=tasks,
        approvals=approvals,
    )
    venue = await database.fetch_one(
        "SELECT id, name FROM venues WHERE id = ?",
        (venue_id,),
    )
    users = await database.fetch_all(
        """
        SELECT id, username, display_name, department, job_title, role
        FROM users WHERE venue_id = ?
        """,
        (venue_id,),
    )
    user_lookup: dict[str, dict[str, Any]] = {}
    for user in users:
        user_lookup[str(user["id"])] = user
        user_lookup[str(user["username"])] = user

    source_message = None
    if event.get("push_id"):
        source_message = await database.fetch_one(
            """
            SELECT message_id, trace_id, session_id, user_id, channel, status,
                   content, reply_text, target_agent, result_json,
                   created_at, updated_at, processed_at
            FROM message_runs
            WHERE venue_id = ? AND message_id = ?
            """,
            (venue_id, event.get("push_id")),
        )
    if source_message is None:
        linked_activity = next(
            (activity for activity in activities if activity.get("session_id")),
            None,
        )
        if linked_activity:
            source_message = await database.fetch_one(
                """
                SELECT message_id, trace_id, session_id, user_id, channel, status,
                       content, reply_text, target_agent, result_json,
                       created_at, updated_at, processed_at
                FROM message_runs
                WHERE venue_id = ? AND session_id = ?
                ORDER BY created_at ASC LIMIT 1
                """,
                (venue_id, linked_activity["session_id"]),
            )

    attachments_by_message = await load_message_attachments(
        database,
        venue_id=venue_id,
        message_ids=(
            [source_message["message_id"]]
            if source_message and source_message.get("message_id")
            else []
        ),
    )
    event_attachments = (
        attachments_by_message.get(source_message["message_id"], [])
        if source_message
        else []
    )

    session = None
    if source_message and source_message.get("session_id"):
        session = await database.fetch_one(
            """
            SELECT session_id, user_id, stage, history_summary, created_at, updated_at
            FROM sessions WHERE venue_id = ? AND session_id = ?
            """,
            (venue_id, source_message["session_id"]),
        )

    reporter_user = user_lookup.get(str(event.get("from_user") or ""))
    if reporter_user is None and source_message:
        reporter_user = user_lookup.get(str(source_message.get("user_id") or ""))
    reporter = _person(reporter_user, "现场员工")
    assignee = _person(
        user_lookup.get(str(event.get("assigned_to") or "")),
        "未分配负责人",
    )

    task_by_id = {str(task["id"]): task for task in tasks}
    task_business_by_id = {
        str(task["id"]): task.get("business_id") or "任务编号待生成"
        for task in tasks
    }
    readable_tasks = []
    for task in tasks:
        dependency_cards = []
        for dependency_id in _decode_json(task.get("dependencies"), []):
            dependency = task_by_id.get(str(dependency_id))
            dependency_cards.append(
                {
                    "business_id": task_business_by_id.get(
                        str(dependency_id),
                        "关联任务不存在或已删除",
                    ),
                    "description": (
                        dependency.get("description")
                        if dependency
                        else "关联任务不存在或已删除"
                    ),
                }
            )
        readable_tasks.append(
            {
                "business_id": task.get("business_id") or "任务编号待生成",
                "description": task.get("description") or "未命名任务",
                "status": task.get("status") or "PENDING",
                "status_label": TASK_STATUS_LABELS.get(
                    str(task.get("status") or "PENDING").upper(),
                    "状态待确认",
                ),
                "assignee": _person(
                    user_lookup.get(str(task.get("assigned_user_id") or "")),
                    "未分配负责人",
                ),
                "due_at": task.get("due_at"),
                "dependencies": dependency_cards,
                "result": _task_result(task.get("result")),
                "evidence": _decode_json(task.get("evidence_refs_json"), []),
                "block_reason": task.get("block_reason"),
                "created_at": task.get("created_at"),
                "updated_at": task.get("updated_at"),
                "completed_at": task.get("completed_at"),
                "technical": {"task_id": task.get("id")},
            }
        )

    readable_approvals = []
    for approval in approvals:
        arguments = _decode_json(approval.get("args"), {})
        execution_result = _decode_json(approval.get("execution_result"), {})
        status = str(approval.get("status") or "PENDING").upper()
        execution_status = str(
            approval.get("execution_status") or "NOT_STARTED"
        ).upper()
        readable_approvals.append(
            {
                "business_id": approval.get("business_id") or "审批编号待生成",
                "action": TOOL_LABELS.get(
                    str(approval.get("tool_name") or ""),
                    "受控业务动作",
                ),
                "status": status,
                "status_label": APPROVAL_STATUS_LABELS.get(status, "状态待确认"),
                "execution_status": execution_status,
                "execution_status_label": EXECUTION_STATUS_LABELS.get(
                    execution_status,
                    "执行状态待确认",
                ),
                "requester": _person(
                    user_lookup.get(
                        str(
                            approval.get("requested_by")
                            or approval.get("user_id")
                            or ""
                        )
                    ),
                    "业务申请人",
                ),
                "reviewer": _person(
                    user_lookup.get(str(approval.get("reviewed_by") or "")),
                    "尚未审核",
                ),
                "task_business_id": task_business_by_id.get(
                    str(approval.get("task_id") or ""),
                    "未关联任务",
                ),
                "message": arguments.get("message") or "暂无动作说明",
                "recipient": arguments.get("recipient") or "收件范围待确认",
                "priority": arguments.get("priority") or "normal",
                "comment": approval.get("comment") or "暂无审核意见",
                "requested_at": approval.get("requested_at"),
                "reviewed_at": approval.get("reviewed_at"),
                "execution_result": execution_result,
                "execution_error": approval.get("execution_error"),
                "evidence_snapshot": _decode_json(
                    approval.get("evidence_snapshot_json"),
                    {},
                ),
                "supersedes_business_id": next(
                    (
                        candidate.get("business_id") or "上一审批编号待生成"
                        for candidate in approvals
                        if candidate.get("approval_id")
                        == approval.get("supersedes_approval_id")
                    ),
                    None,
                ),
                "technical": {
                    "approval_id": approval.get("approval_id"),
                    "tool_name": approval.get("tool_name"),
                },
            }
        )

    watcher_runs = []
    for run in watcher_run_rows:
        watcher_runs.append(
            {
                "id": run.get("id"),
                "status": run.get("status") or "FAILED",
                "summary": run.get("summary") or "闭环检查未返回摘要",
                "model_name": run.get("model_name") or "deepseek-v4-flash",
                "target_count": run.get("target_count") or 0,
                "finding_count": run.get("finding_count") or 0,
                "target_snapshot": _decode_json(
                    run.get("target_snapshot_json"),
                    {},
                ),
                "started_at": run.get("started_at"),
                "completed_at": run.get("completed_at"),
                "trace_id": run.get("trace_id"),
            }
        )

    experience_candidates = []
    source_interview = (
        experience_interview_rows[0] if experience_interview_rows else None
    )
    for candidate in experience_candidate_rows:
        experience_candidates.append(
            {
                "id": candidate.get("id"),
                "business_id": candidate.get("business_id"),
                "source_event_business_id": candidate.get(
                    "source_event_business_id"
                ),
                "title": candidate.get("title") or "待完善的事件经验",
                "applicable_context": candidate.get("applicable_context") or "",
                "signals": _decode_json(candidate.get("signals_json"), []),
                "decision_rule": candidate.get("decision_rule") or "",
                "recommended_actions": _decode_json(
                    candidate.get("recommended_actions_json"),
                    [],
                ),
                "rationale": candidate.get("rationale") or "",
                "prohibitions": _decode_json(
                    candidate.get("prohibitions_json"),
                    [],
                ),
                "exceptions": _decode_json(candidate.get("exceptions_json"), []),
                "source_excerpts": _decode_json(
                    candidate.get("source_excerpts_json"),
                    [],
                ),
                "status": candidate.get("status") or "DRAFT",
                "index_status": candidate.get("index_status") or "NOT_INDEXED",
                "extraction_status": candidate.get("extraction_status") or "PENDING",
                "extraction_model": candidate.get("extraction_model")
                or "deepseek-v4-flash",
                "retryable": bool(candidate.get("retryable")),
                "attempt_count": candidate.get("attempt_count") or 0,
                "created_at": candidate.get("created_at"),
                "updated_at": candidate.get("updated_at"),
                "generated_at": candidate.get("generated_at"),
                "source_interview_id": (
                    source_interview.get("id") if source_interview else None
                ),
                "source_interview_business_id": (
                    source_interview.get("business_id")
                    if source_interview
                    else None
                ),
                "interview_status": (
                    source_interview.get("status") if source_interview else None
                ),
            }
        )

    reference_rows = []
    session_id = (source_message or {}).get("session_id")
    trace_id = event.get("trace_id") or (source_message or {}).get("trace_id")
    if session_id and trace_id:
        reference_rows = await database.fetch_all(
            """
            SELECT references_json, status, started_at, completed_at
            FROM knowledge_retrieval_snapshots
            WHERE venue_id = ? AND (session_id = ? OR trace_id = ?)
            ORDER BY started_at ASC
            """,
            (venue_id, session_id, trace_id),
        )
    elif session_id or trace_id:
        lookup_column = "session_id" if session_id else "trace_id"
        lookup_value = session_id or trace_id
        reference_rows = await database.fetch_all(
            f"""
            SELECT references_json, status, started_at, completed_at
            FROM knowledge_retrieval_snapshots
            WHERE venue_id = ? AND {lookup_column} = ?
            ORDER BY started_at ASC
            """,
            (venue_id, lookup_value),
        )

    references = []
    seen_references = set()
    for reference_row in reference_rows:
        for reference in _decode_json(reference_row.get("references_json"), []):
            key = (
                reference.get("source_type"),
                reference.get("resource_id") or reference.get("source_id"),
                reference.get("version"),
            )
            if key in seen_references:
                continue
            seen_references.add(key)
            references.append(
                {
                    "source_label": reference.get("source_label")
                    or "业务依据",
                    "title": reference.get("title") or "未命名依据",
                    "version": reference.get("version") or "版本待确认",
                    "expert_name": reference.get("expert_name") or None,
                    "publisher_name": reference.get("publisher_name") or None,
                    "published_at": reference.get("published_at"),
                    "relevance": reference.get("relevance")
                    or reference.get("score"),
                    "business_id": reference.get("business_id") or None,
                    "technical": {
                        "source_type": reference.get("source_type"),
                        "resource_id": reference.get("resource_id")
                        or reference.get("source_id"),
                    },
                }
            )

    timeline = []
    for activity in activities:
        payload = _decode_json(activity.get("payload_json"), {})
        actor_user = user_lookup.get(str(activity.get("created_by") or ""))
        if actor_user:
            actor_name = actor_user.get("display_name") or actor_user.get("username")
        elif activity.get("created_by") == event.get("from_user"):
            actor_name = reporter["name"]
        else:
            actor_name = "系统或外部渠道"
        activity_type = str(activity.get("activity_type") or "")
        timeline.append(
            {
                "label": ACTIVITY_LABELS.get(activity_type, "业务状态已更新"),
                "summary": _activity_summary(activity_type, payload),
                "actor_name": actor_name,
                "business_id": payload.get("business_id")
                or payload.get("task_business_id")
                or payload.get("approval_business_id"),
                "created_at": activity.get("created_at"),
                "technical": {
                    "activity_id": activity.get("id"),
                    "activity_type": activity_type,
                    "trace_id": activity.get("trace_id"),
                    "message_id": activity.get("message_id"),
                    "session_id": activity.get("session_id"),
                },
            }
        )

    trace_ids = {
        str(trace_id)
        for trace_id in (
            event.get("trace_id"),
            (source_message or {}).get("trace_id"),
            *(activity.get("trace_id") for activity in activities),
        )
        if trace_id
    }
    model_calls = []
    if trace_ids:
        placeholders = ",".join("?" for _ in trace_ids)
        model_calls = await database.fetch_all(
            f"""
            SELECT id, trace_id, agent_id, agent_name, model_name, status,
                   attempt_count, latency_seconds, error_message, created_at
            FROM llm_call_logs
            WHERE venue_id = ? AND trace_id IN ({placeholders})
            ORDER BY created_at ASC, id ASC
            """,
            (venue_id, *sorted(trace_ids)),
        )

    message_result = _decode_json((source_message or {}).get("result_json"), {})
    agent_trace = (
        message_result.get("agent_trace", [])
        if isinstance(message_result, dict)
        else []
    )
    journey_timeline = list(timeline)
    if source_message and (agent_trace or model_calls):
        journey_timeline.append(
            {
                "label": "员工消息已受理",
                "summary": source_message.get("content") or "员工消息已进入统一助手。",
                "actor_name": reporter["name"],
                "business_id": event.get("business_id"),
                "created_at": source_message.get("created_at"),
                "technical": {
                    "activity_type": "MESSAGE_RECEIVED",
                    "trace_id": source_message.get("trace_id"),
                    "message_id": source_message.get("message_id"),
                    "session_id": source_message.get("session_id"),
                },
            }
        )
        agent_summaries = {
            "ContextTrigger": "识别消息业务情境",
            "Router": "判断统一助手处理路径",
            "MemoryOps": "检索企业知识与经验",
            "Commander": "编排事件处置与下一步",
            "TodoWrite": "生成可执行处置任务",
            "Persona": "结合已授权专家经验生成建议",
            "PersonaExtract": "萃取并结构化专家经验",
            "Watcher": "检查事件闭环证据",
        }
        agent_time = (
            source_message.get("processed_at")
            or source_message.get("updated_at")
            or source_message.get("created_at")
        )
        for index, step in enumerate(agent_trace):
            if not isinstance(step, dict):
                continue
            agent_id = str(step.get("agent_id") or step.get("agent_name") or "Agent")
            journey_timeline.append(
                {
                    "label": agent_summaries.get(agent_id, "统一助手完成业务处理"),
                    "summary": (
                        f"{agent_id} 已完成当前步骤。"
                        if str(step.get("status") or "").lower() not in {"failed", "error"}
                        else f"{agent_id} 处理失败，需要按提示恢复。"
                    ),
                    "actor_name": "企业运营助手",
                    "business_id": event.get("business_id"),
                    "created_at": (
                        float(agent_time) + (index + 1) / 1_000_000
                        if agent_time is not None
                        else None
                    ),
                    "technical": {
                        "activity_type": "AGENT_STEP",
                        "agent_id": agent_id,
                        "agent_name": step.get("agent_name"),
                        "status": step.get("status"),
                        "trace_id": step.get("trace_id")
                        or source_message.get("trace_id"),
                        "message_id": source_message.get("message_id"),
                        "session_id": source_message.get("session_id"),
                    },
                }
            )
        for model_call in model_calls:
            succeeded = str(model_call.get("status") or "").upper() == "SUCCEEDED"
            agent_id = model_call.get("agent_id") or model_call.get("agent_name") or "统一助手"
            journey_timeline.append(
                {
                    "label": "DeepSeek 推理已完成" if succeeded else "DeepSeek 推理失败",
                    "summary": (
                        f"{agent_id} 使用 {model_call.get('model_name') or 'deepseek-v4-flash'} 完成推理。"
                        if succeeded
                        else public_error_message(
                            model_call.get("error_message"),
                            context="model",
                        )
                        or "模型服务处理失败，请携带 Trace ID 联系管理员后重试。"
                    ),
                    "actor_name": "DeepSeek 模型服务",
                    "business_id": event.get("business_id"),
                    "created_at": model_call.get("created_at"),
                    "technical": {
                        "activity_type": (
                            "MODEL_CALL_COMPLETED" if succeeded else "MODEL_CALL_FAILED"
                        ),
                        "model_call_id": model_call.get("id"),
                        "agent_id": agent_id,
                        "trace_id": model_call.get("trace_id"),
                        "message_id": source_message.get("message_id"),
                    },
                }
            )
        for retrieval in reference_rows:
            selected = _decode_json(retrieval.get("references_json"), [])
            journey_timeline.append(
                {
                    "label": "处置依据已检索",
                    "summary": f"已确权并保留 {len(selected)} 条 SOP、案例或专家经验引用。",
                    "actor_name": "企业运营助手",
                    "business_id": event.get("business_id"),
                    "created_at": retrieval.get("completed_at")
                    or retrieval.get("started_at"),
                    "technical": {
                        "activity_type": "KNOWLEDGE_RETRIEVED",
                        "trace_id": source_message.get("trace_id"),
                        "message_id": source_message.get("message_id"),
                    },
                }
            )
        journey_timeline.sort(
            key=lambda entry: (
                float(entry.get("created_at") or 0),
                str((entry.get("technical") or {}).get("activity_type") or ""),
            )
        )

    if str(event.get("status") or "OPEN").upper() == "CLOSED":
        next_action = "事件已闭环，可查看经验沉淀与后续复用情况。"
    elif closure_conditions["blockers"]:
        next_action = closure_conditions["blockers"][0]["message"]
    else:
        next_action = "任务、审批和受控动作均已完成，请运行闭环检查并提交结果。"

    event_status = str(event.get("status") or "OPEN").upper()
    severity = str(event.get("severity") or "P3").upper()
    return sanitize_public_value({
        "summary": {
            "business_id": event.get("business_id") or "事件编号待生成",
            "title": event.get("raw_text") or "未命名现场事件",
            "event_type": event.get("event_type") or "事件类型待确认",
            "severity": severity,
            "severity_label": f"{severity} "
            + ({"P0": "最高优先", "P1": "紧急", "P2": "较高", "P3": "常规", "P4": "低"}.get(severity, "待确认")),
            "status": event_status,
            "status_label": EVENT_STATUS_LABELS.get(event_status, "状态待确认"),
            "source_label": {
                "LIVE": "员工实时上报",
                "HISTORY": "管理员历史补录",
            }.get(str(event.get("source_type") or "").upper(), "业务渠道上报"),
            "venue_name": (venue or {}).get("name") or "当前场地",
            "reporter": reporter,
            "assignee": assignee,
            "reported_at": event.get("created_at") or event.get("confirmed_at"),
            "updated_at": event.get("updated_at") or event.get("confirmed_at"),
            "closed_at": event.get("closed_at"),
            "resolution": event.get("resolution") or "尚未提交闭环结果",
            "next_action": next_action,
            "close_ready": (
                event_status != "CLOSED"
                and closure_conditions["ready"]
            ),
            "closure_conditions": closure_conditions,
        },
        "conversation": (
            {
                "title": f"{reporter['name']}与企业运营助手",
                "channel": (source_message or {}).get("channel") or "业务后台",
                "status": (source_message or {}).get("status") or "已记录",
                "message": (source_message or {}).get("content")
                or event.get("raw_text"),
                "reply": (source_message or {}).get("reply_text")
                or "暂无助手回复记录",
                "session_status": (session or {}).get("stage") or "状态待确认",
                "created_at": (source_message or {}).get("created_at"),
                "technical": {
                    "session_id": session_id,
                    "message_id": (source_message or {}).get("message_id"),
                },
            }
            if source_message
            else None
        ),
        "tasks": readable_tasks,
        "approvals": readable_approvals,
        "references": references,
        "watcher_runs": watcher_runs,
        "experience_candidates": experience_candidates,
        "attachments": event_attachments,
        "timeline": timeline,
        "journey_timeline": journey_timeline,
        "technical": {
            "event_id": event.get("event_id"),
            "trace_id": trace_id,
            "vector_doc_id": event.get("vector_doc_id"),
            "session_id": session_id,
            "message_id": (source_message or {}).get("message_id"),
        },
    })
