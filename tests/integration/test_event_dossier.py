import json
import time

import httpx
import pytest

from src.memory_palace.core.event_activities import append_event_activity
from src.memory_palace.core.event_dossier import build_event_dossier
from src.memory_palace.knowledge.db_client import AsyncDBClient, save_confirmed_event
from src.memory_palace.knowledge.db_init import init_database
from tests.integration.test_mvp_business_apis import build_app, login


class VectorStoreStub:
    def __init__(self):
        self.documents = {}

    def upsert_experience(self, text, metadata, document_id, strict=False):
        self.documents[document_id] = {"text": text, "metadata": metadata}
        return True

    def delete_experience(self, document_id, strict=False):
        self.documents.pop(document_id, None)
        return True


@pytest.mark.asyncio
async def test_event_dossier_is_human_readable_and_keeps_technical_ids_folded(tmp_path):
    database = AsyncDBClient(tmp_path / "event-dossier.db")
    await init_database(database)
    now = time.time()
    await database.execute(
        """
        INSERT INTO venues (id, name, status, created_at, updated_at)
        VALUES (?, ?, 'ACTIVE', ?, ?)
        """,
        ("venue-yueshan", "悦山景区", now, now),
    )
    for user in (
        (
            "user-liming",
            "liming",
            "李明",
            "现场运营部",
            "东门运营员",
            "operator",
        ),
        (
            "user-wangfang",
            "wangfang",
            "王芳",
            "运营管理部",
            "值班经理",
            "manager",
        ),
    ):
        await database.execute(
            """
            INSERT INTO users (
                id, username, password_hash, display_name, department,
                job_title, role, venue_id, status, created_at, updated_at
            ) VALUES (?, ?, 'test-hash', ?, ?, ?, ?, 'venue-yueshan',
                'ACTIVE', ?, ?)
            """,
            (*user, now, now),
        )
    await database.execute(
        """
        INSERT INTO sessions (
            session_id, user_id, stage, created_at, updated_at, venue_id,
            history_summary
        ) VALUES (?, ?, 'ACTIVE', ?, ?, ?, ?)
        """,
        (
            "session-event-dossier",
            "user-liming",
            now,
            now,
            "venue-yueshan",
            "李明上报观光车轮端异响",
        ),
    )
    await database.execute(
        """
        INSERT INTO message_runs (
            message_id, trace_id, session_id, user_id, venue_id, content,
            status, channel, reply_text, target_agent, result_json,
            created_at, updated_at, processed_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'COMPLETED', 'WECOM_SIMULATOR', ?, ?, ?, ?, ?, ?)
        """,
        (
            "message-event-dossier",
            "trace-event-dossier",
            "session-event-dossier",
            "user-liming",
            "venue-yueshan",
            "12号观光车右后轮有金属摩擦声。",
            "事件已受理，正在安排现场检查。",
            "commander",
            json.dumps(
                {
                    "agent_trace": [
                        {"agent_id": agent_id, "status": "completed", "trace_id": "trace-event-dossier"}
                        for agent_id in ("ContextTrigger", "Router", "MemoryOps", "Commander")
                    ]
                },
                ensure_ascii=False,
            ),
            now,
            now,
            now,
        ),
    )
    await database.execute(
        """
        INSERT INTO llm_call_logs (
            id, venue_id, trace_id, agent_id, agent_name, model_name,
            status, attempt_count, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'SUCCEEDED', 1, ?)
        """,
        (
            "llm-event-dossier-router",
            "venue-yueshan",
            "trace-event-dossier",
            "Router",
            "router",
            "deepseek-flash",
            now + 0.01,
        ),
    )
    await database.execute(
        """
        INSERT INTO message_attachments (
            id, business_id, venue_id, owner_user_id, original_name,
            content_type, size_bytes, sha256, scan_status, scan_engine,
            storage_key, external_ref, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PASSED', ?, ?, ?, ?)
        """,
        (
            "attachment-event-dossier",
            "FJ-20260729-WHEEL",
            "venue-yueshan",
            "user-liming",
            "右后轮现场.png",
            "image/png",
            2048,
            "attachment-sha256",
            "MVP_SIGNATURE_SCAN_V1",
            "private/object/key.png",
            "/api/v1/assistant/attachments/attachment-event-dossier/content",
            now + 0.02,
        ),
    )
    await database.execute(
        """
        INSERT INTO message_attachment_links (
            id, venue_id, message_id, attachment_id, description, linked_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "attachment-link-event-dossier",
            "venue-yueshan",
            "message-event-dossier",
            "attachment-event-dossier",
            "右后轮内侧有水迹，车辆已断电。",
            now + 0.03,
        ),
    )

    event_id = await save_confirmed_event(
        push_id="message-event-dossier",
        from_user="user-liming",
        raw_text="12号观光车右后轮有金属摩擦声。",
        event_type="车辆异响",
        severity="P1",
        context_trigger_data={"location": "东门停车区"},
        venue_id="venue-yueshan",
        trace_id="trace-event-dossier",
        database=database,
        vector_client=VectorStoreStub(),
    )
    await database.execute(
        """
        UPDATE confirmed_events SET assigned_to = ?
        WHERE venue_id = ? AND event_id = ?
        """,
        ("user-wangfang", "venue-yueshan", event_id),
    )
    event = await database.fetch_one(
        "SELECT * FROM confirmed_events WHERE venue_id = ? AND event_id = ?",
        ("venue-yueshan", event_id),
    )

    await database.execute(
        """
        INSERT INTO tasks (
            id, business_id, venue_id, session_id, event_id, description,
            status, dependencies, result, evidence_refs_json,
            assigned_user_id, created_at, updated_at, completed_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'DONE', '[]', ?, ?, ?, ?, ?, ?)
        """,
        (
            "task-inspection-internal-id",
            "RW-20260729-INSPECT",
            "venue-yueshan",
            "session-event-dossier",
            event_id,
            "检查右后轮护板间隙并完成三轮空载试车",
            json.dumps(
                {"trial_runs": 3, "temperature_c": 33.2, "result": "无异响"},
                ensure_ascii=False,
            ),
            json.dumps([{"name": "三轮试车记录"}], ensure_ascii=False),
            "user-liming",
            now + 60,
            now + 900,
            now + 900,
        ),
    )
    await append_event_activity(
        database,
        venue_id="venue-yueshan",
        event_id=event_id,
        activity_type="TASK_COMPLETED",
        created_by="user-liming",
        session_id="session-event-dossier",
        trace_id="trace-task-completed",
        payload={
            "business_id": "RW-20260729-INSPECT",
            "summary": "完成三轮空载试车，无异响，温度正常。",
        },
        idempotency_key="task-completed:task-inspection-internal-id",
        created_at=now + 900,
    )
    await database.execute(
        """
        INSERT INTO approval_requests (
            approval_id, business_id, venue_id, tool_name, args, session_id,
            event_id, task_id, user_id, requested_at, requested_by, status,
            evidence_snapshot_json, execution_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, 'NOT_STARTED')
        """,
        (
            "approval-notify-internal-id",
            "SP-20260729-NOTIFY",
            "venue-yueshan",
            "send_in_app_alert",
            json.dumps(
                {
                    "message": "12号车停运观察，启用7号备用车。",
                    "recipient": "调度组",
                    "priority": "high",
                },
                ensure_ascii=False,
            ),
            "session-event-dossier",
            event_id,
            "task-inspection-internal-id",
            "user-wangfang",
            now + 960,
            "user-wangfang",
            json.dumps(
                {"task_business_id": "RW-20260729-INSPECT", "result": "无异响"},
                ensure_ascii=False,
            ),
        ),
    )
    await append_event_activity(
        database,
        venue_id="venue-yueshan",
        event_id=event_id,
        activity_type="APPROVAL_REQUESTED",
        created_by="user-wangfang",
        session_id="session-event-dossier",
        trace_id="trace-approval-requested",
        payload={
            "business_id": "SP-20260729-NOTIFY",
            "summary": "申请向调度组发送车辆停运与备用车通知。",
        },
        idempotency_key="approval-requested:approval-notify-internal-id",
        created_at=now + 960,
    )
    await database.execute(
        """
        INSERT INTO knowledge_retrieval_snapshots (
            id, schema_version, venue_id, trace_id, message_id, session_id,
            agent_id, query_summary, query_sha256, backend, index_name, status,
            top_k, similarity_threshold, filter_json, attempts_json,
            references_json, raw_hit_count, selected_count, started_at,
            completed_at, latency_ms
        ) VALUES (?, 1, ?, ?, ?, ?, 'MemoryOps', ?, ?, 'pgvector', 'knowledge',
            'SUCCEEDED', 5, 0.6, '{}', '[]', ?, 1, 1, ?, ?, 120)
        """,
        (
            "snapshot-event-dossier",
            "venue-yueshan",
            "trace-event-dossier",
            "message-event-dossier",
            "session-event-dossier",
            "观光车雨后异响处置",
            "query-sha256",
            json.dumps(
                [
                    {
                        "source_type": "SOP",
                        "source_label": "已发布 SOP",
                        "resource_id": "sop-vehicle-rain",
                        "title": "观光车雨后复运与异常异响处置",
                        "version": "2.1",
                        "publisher_name": "赵敏",
                        "relevance": 0.94,
                    }
                ],
                ensure_ascii=False,
            ),
            now + 15,
            now + 15.12,
        ),
    )

    dossier = await build_event_dossier(
        database,
        event=event,
        venue_id="venue-yueshan",
    )

    assert dossier["summary"]["business_id"].startswith("SJ-")
    assert dossier["summary"]["venue_name"] == "悦山景区"
    assert dossier["summary"]["reporter"]["name"] == "李明"
    assert dossier["summary"]["assignee"]["name"] == "王芳"
    assert dossier["summary"]["status_label"] == "处理中"
    assert event_id not in json.dumps(dossier["summary"], ensure_ascii=False)
    assert dossier["conversation"]["title"] == "李明与企业运营助手"
    assert dossier["attachments"] == [
        {
            "attachment_id": "attachment-event-dossier",
            "business_id": "FJ-20260729-WHEEL",
            "name": "右后轮现场.png",
            "content_type": "image/png",
            "size_bytes": 2048,
            "sha256": "attachment-sha256",
            "scan_status": "PASSED",
            "scan_engine": "MVP_SIGNATURE_SCAN_V1",
            "external_ref": "/api/v1/assistant/attachments/attachment-event-dossier/content",
            "thumbnail_url": "/api/v1/assistant/attachments/attachment-event-dossier/content",
            "description": "右后轮内侧有水迹，车辆已断电。",
            "uploaded_by": "user-liming",
            "uploaded_by_name": "李明",
            "created_at": now + 0.02,
        }
    ]
    assert "private/object/key.png" not in json.dumps(
        dossier["attachments"],
        ensure_ascii=False,
    )
    assert dossier["tasks"][0]["business_id"] == "RW-20260729-INSPECT"
    assert dossier["tasks"][0]["result"]["fields"]["temperature_c"] == 33.2
    assert dossier["approvals"][0]["business_id"] == "SP-20260729-NOTIFY"
    assert dossier["approvals"][0]["task_business_id"] == "RW-20260729-INSPECT"
    assert dossier["references"][0]["title"] == "观光车雨后复运与异常异响处置"
    assert [entry["label"] for entry in dossier["timeline"]] == [
        "事件已受理",
        "任务已完成",
        "受控动作待审批",
    ]
    journey_types = [entry["technical"]["activity_type"] for entry in dossier["journey_timeline"]]
    assert "MESSAGE_RECEIVED" in journey_types
    assert journey_types.count("AGENT_STEP") == 4
    assert "MODEL_CALL_COMPLETED" in journey_types
    assert "KNOWLEDGE_RETRIEVED" in journey_types
    assert any(
        entry["label"] == "DeepSeek 推理已完成" and "deepseek-flash" in entry["summary"]
        for entry in dossier["journey_timeline"]
    )
    assert dossier["technical"]["event_id"] == event_id
    assert dossier["tasks"][0]["technical"]["task_id"] == "task-inspection-internal-id"
    assert dossier["approvals"][0]["technical"]["approval_id"] == "approval-notify-internal-id"

    activity_rows = await database.fetch_all(
        "SELECT activity_type FROM event_activities WHERE event_id = ? ORDER BY created_at",
        (event_id,),
    )
    assert [row["activity_type"] for row in activity_rows] == [
        "EVENT_CREATED",
        "TASK_COMPLETED",
        "APPROVAL_REQUESTED",
    ]
    await database.close()


@pytest.mark.asyncio
async def test_admin_event_detail_returns_tenant_scoped_readable_dossier(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(
            client,
            "mvp-admin",
            "Mvp-Admin-Password-2026",
        )
        principal = await client.get("/auth/me", headers=admin_headers)
        created = await client.post(
            "/admin/events",
            headers=admin_headers,
            json={
                "raw_text": "东门闸机反复离线，现场已切换人工检票。",
                "event_type": "设施故障",
                "severity": "P1",
                "from_user": principal.json()["id"],
            },
        )
        assert created.status_code == 200, created.text
        event_id = created.json()["event_id"]

        detail = await client.get(
            f"/admin/events/{event_id}",
            headers=admin_headers,
        )
        foreign = await client.get(
            "/admin/events/other-venue-event",
            headers=admin_headers,
        )

    assert detail.status_code == 200, detail.text
    payload = detail.json()
    assert payload["event_id"] == event_id
    assert payload["business_id"].startswith("SJ-")
    assert payload["dossier"]["summary"]["business_id"] == payload["business_id"]
    assert payload["dossier"]["summary"]["reporter"]["name"] == "交付管理员"
    assert payload["dossier"]["summary"]["source_label"] == "管理员历史补录"
    assert payload["dossier"]["timeline"][0]["label"] == "事件已受理"
    assert payload["dossier"]["technical"]["event_id"] == event_id
    assert event_id not in json.dumps(
        payload["dossier"]["summary"],
        ensure_ascii=False,
    )
    assert foreign.status_code == 404
    assert foreign.json()["detail"]["code"] == "EVENT_NOT_FOUND"
    await database.close()


@pytest.mark.asyncio
async def test_event_dossier_includes_persisted_watcher_and_experience_candidate(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(
            client,
            "mvp-admin",
            "Mvp-Admin-Password-2026",
        )
        principal = (await client.get("/auth/me", headers=admin_headers)).json()
        created = await client.post(
            "/admin/events",
            headers=admin_headers,
            json={
                "raw_text": "观光车雨后出现轮端间歇性金属异响。",
                "event_type": "车辆故障",
                "severity": "P1",
                "from_user": principal["id"],
            },
        )
        assert created.status_code == 200, created.text
        event_id = created.json()["event_id"]
        event_row = await database.fetch_one(
            "SELECT business_id FROM confirmed_events WHERE event_id = ?",
            (event_id,),
        )
        event_business_id = event_row["business_id"]
        now = time.time()
        await database.execute(
            """
            INSERT INTO watcher_policies (
                id, venue_id, name, description, schedule_cron, enabled,
                check_types_json, config_json, version, created_by,
                created_at, updated_at
            ) VALUES (?, ?, ?, '', '0 10 * * *', ?, '[]', '{}', 1, ?, ?, ?)
            """,
            (
                "policy-event-dossier",
                principal["venue_id"],
                "事件闭环证据检查",
                True,
                principal["id"],
                now,
                now,
            ),
        )
        await database.execute(
            """
            INSERT INTO watcher_runs (
                id, policy_id, venue_id, event_id, trigger_source, status,
                trace_id, model_name, target_count, finding_count, summary,
                target_snapshot_json, result_json, started_at, completed_at
            ) VALUES (?, ?, ?, ?, 'EVENT_MANUAL', 'SUCCEEDED', ?, ?, 6, 0,
                ?, ?, '{}', ?, ?)
            """,
            (
                "watcher-run-event-dossier",
                "policy-event-dossier",
                principal["venue_id"],
                event_id,
                "trace-watcher-event-dossier",
                "deepseek-flash",
                "证据完整，可闭环",
                json.dumps(
                    {
                        "schema_version": 1,
                        "messages": [{"business_summary": "员工已上报异响"}],
                        "knowledge_references": [{"title": "车辆异响 SOP"}],
                        "tasks": [],
                        "approvals": [],
                        "notifications": [],
                    },
                    ensure_ascii=False,
                ),
                now + 1,
                now + 2,
            ),
        )
        await database.execute(
            """
            INSERT INTO experience_interviews (
                id, business_id, venue_id, expert_id, title, source_event_id,
                status, current_question_index, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'INVITED', 0, ?, ?, ?)
            """,
            (
                "interview-event-dossier",
                "FT-20260730-RAIN",
                principal["venue_id"],
                "expert-event-dossier",
                "雨后观光车轮端异响复盘",
                event_id,
                principal["id"],
                now + 2.1,
                now + 2.1,
            ),
        )
        await database.execute(
            """
            INSERT INTO experience_candidates (
                id, business_id, venue_id, source_event_id,
                source_event_business_id, title, applicable_context,
                signals_json, decision_rule, recommended_actions_json,
                rationale, prohibitions_json, exceptions_json,
                source_excerpts_json, status, index_status,
                extraction_status, extraction_model, retryable,
                attempt_count, created_by, created_at, updated_at, generated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'DRAFT',
                'NOT_INDEXED', 'SUCCEEDED', 'deepseek-flash', ?, 1, ?, ?, ?, ?)
            """,
            (
                "candidate-event-dossier",
                "JY-20260730-RAIN",
                principal["venue_id"],
                event_id,
                event_business_id,
                "雨后观光车轮端异响判断",
                "雨后复运检查",
                json.dumps(["异响随轮速变化"], ensure_ascii=False),
                "先检查护板间隙，再进行空载低速试车",
                json.dumps(["校正护板并复测"], ensure_ascii=False),
                "避免未经验证直接载客",
                json.dumps(["出现焦味时禁止继续试车"], ensure_ascii=False),
                json.dumps(["制动跑偏时拖车检修"], ensure_ascii=False),
                json.dumps(["完成三轮空载试车，无异响"], ensure_ascii=False),
                False,
                principal["id"],
                now + 3,
                now + 4,
                now + 4,
            ),
        )

        detail = await client.get(
            f"/admin/events/{event_id}",
            headers=admin_headers,
        )

    assert detail.status_code == 200, detail.text
    dossier = detail.json()["dossier"]
    assert dossier["watcher_runs"][0]["summary"] == "证据完整，可闭环"
    assert dossier["watcher_runs"][0]["model_name"] == "deepseek-flash"
    assert dossier["watcher_runs"][0]["target_snapshot"]["schema_version"] == 1
    candidate = dossier["experience_candidates"][0]
    assert candidate["business_id"] == "JY-20260730-RAIN"
    assert candidate["status"] == "DRAFT"
    assert candidate["index_status"] == "NOT_INDEXED"
    assert candidate["signals"] == ["异响随轮速变化"]
    assert candidate["source_interview_id"] == "interview-event-dossier"
    assert candidate["source_interview_business_id"] == "FT-20260730-RAIN"
    assert candidate["interview_status"] == "INVITED"
    assert "event_snapshot_json" not in candidate
    await database.close()


@pytest.mark.asyncio
async def test_event_dossier_reads_agent_model_calls_without_message_source(tmp_path):
    database = AsyncDBClient(tmp_path / "event-dossier-agent.db")
    await init_database(database)
    now = time.time()
    await database.execute(
        """
        INSERT INTO venues (id, name, status, created_at, updated_at)
        VALUES (?, ?, 'ACTIVE', ?, ?)
        """,
        ("venue-agent", "Agent 测试景区", now, now),
    )
    event_id = await save_confirmed_event(
        push_id="manual",
        from_user="scenic-simulation-ops",
        raw_text="雨后 12 号观光车右后轮异常",
        event_type="设备安全",
        severity="P1",
        context_trigger_data={"source": "ticket-08"},
        source_type="SCENIC_ALERT",
        venue_id="venue-agent",
        trace_id="a" * 32,
        database=database,
        vector_client=VectorStoreStub(),
    )
    trace_id = "b" * 32
    await append_event_activity(
        database,
        venue_id="venue-agent",
        event_id=event_id,
        activity_type="ADVICE_READY",
        trace_id=trace_id,
        payload={"summary": "继续停运并检查右后轮。"},
        idempotency_key="advice-ready-ticket-08",
    )
    await database.execute(
        """
        INSERT INTO llm_call_logs (
            id, venue_id, trace_id, agent_id, agent_name, provider, model_name,
            status, attempt_count, latency_seconds, prompt_tokens,
            completion_tokens, total_tokens, request_id, is_mock, created_at
        ) VALUES (?, ?, ?, 'MemoryOps', 'MemoryOps', 'deepseek', 'deepseek-flash',
                  'SUCCEEDED', 1, 1.25, 120, 30, 150, 'request-1', 0, ?)
        """,
        ("call-ticket-08", "venue-agent", trace_id, now),
    )

    event = await database.fetch_one(
        "SELECT * FROM confirmed_events WHERE event_id = ?",
        (event_id,),
    )
    dossier = await build_event_dossier(database, event=event, venue_id="venue-agent")

    assert dossier["model_calls"] == [
        {
            "model_call_id": "call-ticket-08",
            "trace_id": trace_id,
            "agent_id": "MemoryOps",
            "agent_name": "MemoryOps",
            "provider": "deepseek",
            "model_name": "deepseek-flash",
            "status": "SUCCEEDED",
            "attempt_count": 1,
            "latency_seconds": 1.25,
            "prompt_tokens": 120,
            "completion_tokens": 30,
            "total_tokens": 150,
            "request_id": "request-1",
            "error_message": None,
            "is_mock": False,
            "created_at": now,
        }
    ]
    assert any(
        entry["technical"]["activity_type"] == "MODEL_CALL_COMPLETED"
        and entry["technical"]["model_call_id"] == "call-ticket-08"
        for entry in dossier["journey_timeline"]
    )
    await database.close()


@pytest.mark.asyncio
async def test_same_millisecond_event_activities_keep_append_order(tmp_path):
    database = AsyncDBClient(tmp_path / "event-activity-order.db")
    await init_database(database)
    now = time.time()
    await database.execute(
        """
        INSERT INTO venues (id, name, status, created_at, updated_at)
        VALUES (?, ?, 'ACTIVE', ?, ?)
        """,
        ("venue-order", "\u6392\u5e8f\u666f\u533a", now, now),
    )
    event_id = await save_confirmed_event(
        push_id="manual",
        from_user="scenic-simulation-ops",
        raw_text="\u4efb\u52a1\u540c\u4e00\u6beb\u79d2\u963b\u585e\u5e76\u89e3\u9664",
        event_type="\u8bbe\u5907\u5b89\u5168",
        severity="P2",
        context_trigger_data={"source": "ordering-regression"},
        source_type="SCENIC_ALERT",
        venue_id="venue-order",
        trace_id="c" * 32,
        database=database,
        vector_client=VectorStoreStub(),
    )
    frozen = now + 5
    blocked = await append_event_activity(
        database,
        venue_id="venue-order",
        event_id=event_id,
        activity_type="TASK_BLOCKED",
        trace_id="d" * 32,
        payload={"summary": "\u73b0\u573a\u963b\u788d"},
        idempotency_key="order-blocked",
        created_at=frozen,
    )
    unblocked = await append_event_activity(
        database,
        venue_id="venue-order",
        event_id=event_id,
        activity_type="TASK_UNBLOCKED",
        trace_id="e" * 32,
        payload={"summary": "\u963b\u788d\u5df2\u89e3\u9664"},
        idempotency_key="order-unblocked",
        created_at=frozen,
    )

    assert unblocked["created_at"] > blocked["created_at"]

    event = await database.fetch_one(
        "SELECT * FROM confirmed_events WHERE event_id = ?",
        (event_id,),
    )
    dossier = await build_event_dossier(database, event=event, venue_id="venue-order")
    ordered = [
        entry["technical"]["activity_type"]
        for entry in dossier["timeline"]
        if entry["technical"]["activity_type"]
        in {"TASK_BLOCKED", "TASK_UNBLOCKED"}
    ]
    assert ordered == ["TASK_BLOCKED", "TASK_UNBLOCKED"]
    await database.close()
