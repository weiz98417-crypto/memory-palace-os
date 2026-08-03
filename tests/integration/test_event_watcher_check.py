import json
import time

import httpx
import pytest
from loguru import logger

from src.memory_palace.core.skill_base import SkillOutput
from src.memory_palace.core.sensitive_output import public_error_message
from tests.integration.test_mvp_business_apis import build_app, create_user, login


async def _seed_complete_event(database, *, event_id: str = "event-watcher-ready") -> str:
    now = time.time()
    session_id = "session-watcher-ready"
    message_id = "message-watcher-source"
    trace_id = "trace-event-watcher-ready"
    await database.execute(
        """
        INSERT INTO sessions (
            session_id, user_id, stage, created_at, updated_at, venue_id
        ) VALUES (?, ?, 'ACTIVE', ?, ?, 'venue-alpha')
        """,
        (session_id, "mvp-admin", now - 600, now - 30),
    )
    for index, content in enumerate(("东门闸机无法核验门票。", "已更换读卡器并完成三次核验。")):
        await database.execute(
            """
            INSERT INTO message_runs (
                message_id, trace_id, session_id, user_id, venue_id, content,
                status, channel, reply_text, result_json, created_at,
                updated_at, processed_at
            ) VALUES (?, ?, ?, ?, 'venue-alpha', ?, 'COMPLETED',
                'WECOM_SIMULATOR', ?, '{}', ?, ?, ?)
            """,
            (
                message_id if index == 0 else "message-watcher-followup",
                trace_id if index == 0 else "trace-event-watcher-followup",
                session_id,
                "mvp-admin",
                content,
                "事件已受理" if index == 0 else "现场结果已记录",
                now - 600 + index * 420,
                now - 590 + index * 420,
                now - 590 + index * 420,
            ),
        )
    await database.execute(
        """
        INSERT INTO confirmed_events (
            event_id, business_id, push_id, from_user, raw_text, event_type,
            severity, context_trigger_data, memory_content, created_at,
            confirmed_at, venue_id, source_type, status, assigned_to,
            trace_id, updated_at
        ) VALUES (?, 'SJ-20260730-WATCHER', ?, 'mvp-admin', ?, '设备故障',
            'P3', '{}', ?, ?, ?, 'venue-alpha', 'LIVE', 'OPEN',
            'mvp-admin', ?, ?)
        """,
        (
            event_id,
            message_id,
            "东门闸机无法核验门票。",
            "东门闸机故障处置",
            now - 600,
            now - 590,
            trace_id,
            now - 30,
        ),
    )
    await database.execute(
        """
        INSERT INTO tasks (
            id, business_id, venue_id, session_id, event_id, description,
            status, dependencies, result_schema_json, evidence_refs_json,
            result, assigned_user_id, created_at, updated_at, completed_at
        ) VALUES ('task-watcher-ready', 'RW-20260730-WATCHER', 'venue-alpha',
            ?, ?, '更换读卡器并完成三次核验', 'DONE', '[]', '{}', ?, ?,
            'mvp-admin', ?, ?, ?)
        """,
        (
            session_id,
            event_id,
            json.dumps([{"name": "三次核验记录"}], ensure_ascii=False),
            json.dumps({"checks": 3, "result": "全部通过"}, ensure_ascii=False),
            now - 500,
            now - 120,
            now - 120,
        ),
    )
    await database.execute(
        """
        INSERT INTO approval_requests (
            approval_id, business_id, venue_id, tool_name, args, session_id,
            event_id, task_id, user_id, requested_at, requested_by,
            evidence_snapshot_json, status, reviewed_at, reviewed_by,
            comment, correlation_trace_id, execution_trace_id,
            execution_status, execution_result
        ) VALUES ('approval-watcher-ready', 'SP-20260730-WATCHER',
            'venue-alpha', 'send_in_app_alert', ?, ?, ?,
            'task-watcher-ready', 'mvp-admin', ?, 'mvp-admin', ?, 'APPROVED',
            ?, 'mvp-admin', '同意通知恢复通行', ?, ?, 'SUCCEEDED', ?)
        """,
        (
            json.dumps(
                {"recipient": "东门运营组", "message": "闸机已恢复通行"},
                ensure_ascii=False,
            ),
            session_id,
            event_id,
            now - 110,
            json.dumps({"task_result": "三次核验通过"}, ensure_ascii=False),
            now - 100,
            trace_id,
            "trace-notification-watcher-ready",
            json.dumps({"status": "DELIVERED", "sent": True}, ensure_ascii=False),
        ),
    )
    references = [
        {
            "source_type": "SOP",
            "resource_id": "sop-gate-recovery",
            "title": "闸机故障恢复 SOP",
            "version": "v2",
        }
    ]
    await database.execute(
        """
        INSERT INTO knowledge_retrieval_snapshots (
            id, schema_version, venue_id, trace_id, message_id, session_id,
            agent_id, query_summary, query_sha256, backend, index_name,
            status, top_k, similarity_threshold, filter_json, attempts_json,
            references_json, raw_hit_count, selected_count, started_at,
            completed_at, latency_ms
        ) VALUES ('retrieval-watcher-ready', 1, 'venue-alpha', ?, ?, ?,
            'MemoryOps', '闸机恢复流程', 'sha-watcher-ready', 'chroma',
            'knowledge', 'SUCCEEDED', 5, 0.6, '{}', '[]', ?, 1, 1, ?, ?, 80)
        """,
        (
            trace_id,
            message_id,
            session_id,
            json.dumps(references, ensure_ascii=False),
            now - 560,
            now - 559,
        ),
    )
    await database.execute(
        """
        INSERT INTO push_logs (
            push_id, venue_id, msg_id, from_user, raw_text, event_type,
            severity, stage1_triggered, hit_keywords, pushed_at,
            adoption_status, trace_id, channel, recipient, delivery_status,
            idempotency_key
        ) VALUES ('push-watcher-ready', 'venue-alpha', ?, 'mvp-admin', ?,
            '设备恢复通知', 'P3', 0, '[]', ?, 'adopted', ?, 'in_app',
            '东门运营组', 'DELIVERED', 'push-watcher-ready')
        """,
        (
            message_id,
            "闸机已恢复通行",
            now - 90,
            "trace-notification-watcher-ready",
        ),
    )
    return event_id


@pytest.mark.asyncio
async def test_event_watcher_check_persists_complete_evidence_snapshot(tmp_path, monkeypatch):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    event_id = await _seed_complete_event(database)
    observed_context = {}

    async def successful_watcher(self, context, trace_id):
        assert self.model_name == "deepseek-v4-flash"
        observed_context.update(context)
        return SkillOutput(
            success=True,
            reply_text="模型确认处置证据完整。",
            structured_data={
                "is_violation_found": False,
                "escalated_cases": [],
                "audit_score": 100,
            },
            action_taken="sop_compliance_audit",
        )

    monkeypatch.setattr(
        "src.memory_palace.core.watcher_runtime.WatcherSkill.run",
        successful_watcher,
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
            response = await client.post(
                f"/admin/events/{event_id}/watcher-check",
                headers=headers,
            )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["summary"] == "证据完整，可闭环"
        assert body["ready_to_close"] is True
        assert body["model"] == "deepseek-v4-flash"
        assert body["trace_id"] == body["run"]["trace_id"]
        assert body["findings"] == []
        snapshot = body["run"]["target_snapshot"]
        assert len(snapshot["messages"]) == 2
        assert snapshot["knowledge_references"][0]["title"] == "闸机故障恢复 SOP"
        assert snapshot["tasks"][0]["result"] == {"checks": 3, "result": "全部通过"}
        assert snapshot["approvals"][0]["execution_result"]["status"] == "DELIVERED"
        assert snapshot["notifications"][0]["delivery_status"] == "DELIVERED"
        assert snapshot["handling"]["elapsed_seconds"] >= 500
        assert observed_context["audit_target_logs"][0]["case_id"] == event_id

        persisted = await database.fetch_one(
            "SELECT * FROM watcher_runs WHERE id = ?",
            (body["run"]["id"],),
        )
        assert persisted["status"] == "SUCCEEDED"
        assert persisted["event_id"] == event_id
        assert persisted["model_name"] == "deepseek-v4-flash"
        assert json.loads(persisted["target_snapshot_json"]) == snapshot
        audit = await database.fetch_one(
            """
            SELECT outcome, trace_id FROM audit_logs
            WHERE action = 'EVENT_WATCHER_CHECK' AND resource_id = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (event_id,),
        )
        assert audit == {"outcome": "SUCCEEDED", "trace_id": body["trace_id"]}
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_event_watcher_check_sanitizes_evidence_and_model_output(tmp_path, monkeypatch):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    event_id = await _seed_complete_event(database, event_id="event-watcher-sanitized")
    fake_secret = "sk-FAKE-WATCHER-SNAPSHOT-123456789"
    private_prompt = "private employee system instructions"
    private_path = r"C:\private\uploads\watcher-evidence.json"
    await database.execute(
        "UPDATE message_runs SET result_json = ? WHERE message_id = ?",
        (
            json.dumps(
                {
                    "business_result": "three checks passed",
                    "api_key": fake_secret,
                    "system_prompt": private_prompt,
                    "storage_path": private_path,
                }
            ),
            "message-watcher-source",
        ),
    )
    await database.execute(
        "UPDATE push_logs SET delivery_error = ? WHERE push_id = ?",
        (
            (
                "recipient unavailable; "
                f"api_key={fake_secret}; file_path={private_path}"
            ),
            "push-watcher-ready",
        ),
    )
    observed_context = {}

    async def successful_watcher(self, context, trace_id):
        observed_context.update(context)
        return SkillOutput(
            success=True,
            structured_data={
                "is_violation_found": False,
                "escalated_cases": [],
                "audit_score": 100,
                "business_summary": "evidence is complete",
                "api_key": fake_secret,
                "raw_prompt": private_prompt,
                "artifact": {"local_path": private_path},
                "unsafe_echo": f"Bearer {fake_secret}",
            },
        )

    monkeypatch.setattr(
        "src.memory_palace.core.watcher_runtime.WatcherSkill.run",
        successful_watcher,
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
            response = await client.post(
                f"/admin/events/{event_id}/watcher-check",
                headers=headers,
            )

        assert response.status_code == 200, response.text
        body = response.json()
        persisted = await database.fetch_one(
            "SELECT target_snapshot_json, result_json FROM watcher_runs WHERE id = ?",
            (body["run"]["id"],),
        )
        serialized_public_data = json.dumps(
            {
                "watcher_context": observed_context,
                "response": body["run"],
                "persisted": persisted,
            },
            ensure_ascii=False,
        )
        assert fake_secret not in serialized_public_data
        assert private_prompt not in serialized_public_data
        assert "watcher-evidence.json" not in serialized_public_data
        source_message = next(
            message
            for message in body["run"]["target_snapshot"]["messages"]
            if message["message_id"] == "message-watcher-source"
        )
        assert source_message["result"]["business_result"] == "three checks passed"
        assert "recipient unavailable" in body["run"]["target_snapshot"]["notifications"][0][
            "delivery_error"
        ]
        assert body["run"]["result"]["model_output"]["business_summary"] == "evidence is complete"
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_event_watcher_check_does_not_fake_success_when_skill_fails(tmp_path, monkeypatch):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    event_id = await _seed_complete_event(database, event_id="event-watcher-failed")
    raw_failure = (
        "DeepSeek 401 authentication failed; "
        "api_key=sk-FAKE-WATCHER-SECRET-123456789; "
        "system_prompt=private employee instructions; "
        r"file_path=C:\private\uploads\employee-record.txt"
    )

    async def failed_watcher(self, context, trace_id):
        return SkillOutput(
            success=False,
            error_msg=raw_failure,
            action_taken="fatal_error_fallback",
        )

    monkeypatch.setattr(
        "src.memory_palace.core.watcher_runtime.WatcherSkill.run",
        failed_watcher,
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
            response = await client.post(
                f"/admin/events/{event_id}/watcher-check",
                headers=headers,
            )

        assert response.status_code == 502, response.text
        detail = response.json()["detail"]
        assert detail["code"] == "WATCHER_EVENT_CHECK_FAILED"
        assert detail["run_status"] == "FAILED"
        run = await database.fetch_one(
            "SELECT * FROM watcher_runs WHERE id = ?",
            (detail["run_id"],),
        )
        assert run["status"] == "FAILED"
        assert run["completed_at"] is not None
        assert run["error"] == public_error_message(raw_failure, context="operation")
        assert "sk-FAKE-WATCHER" not in run["error"]
        assert "private employee instructions" not in run["error"]
        assert "employee-record.txt" not in run["error"]
        assert json.loads(run["target_snapshot_json"])["event"]["event_id"] == event_id
        assert detail["trace_id"] == run["trace_id"]
        assert await database.fetch_all(
            "SELECT id FROM watcher_findings WHERE run_id = ?",
            (run["id"],),
        ) == []
        audit = await database.fetch_one(
            """
            SELECT outcome, trace_id FROM audit_logs
            WHERE action = 'EVENT_WATCHER_CHECK' AND resource_id = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (event_id,),
        )
        assert audit == {"outcome": "FAILED", "trace_id": run["trace_id"]}
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_event_watcher_check_removes_open_finding_when_run_completion_fails(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    event_id = await _seed_complete_event(
        database,
        event_id="event-watcher-post-persist-failure",
    )

    async def watcher_with_issue(self, context, trace_id):
        return SkillOutput(
            success=True,
            structured_data={
                "is_violation_found": True,
                "escalated_cases": [
                    {
                        "case_id": event_id,
                        "source_type": "event",
                        "issue_type": "DELIVERY_EVIDENCE",
                        "violation_reason": "Recipient confirmation is missing.",
                        "severity_level": "P2",
                    }
                ],
            },
        )

    monkeypatch.setattr(
        "src.memory_palace.core.watcher_runtime.WatcherSkill.run",
        watcher_with_issue,
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
            original_execute = database.execute
            completion_failure_injected = False

            async def fail_run_completion(sql, parameters=()):
                nonlocal completion_failure_injected
                normalized_sql = " ".join(sql.split())
                if (
                    not completion_failure_injected
                    and "UPDATE watcher_runs SET status = 'SUCCEEDED'" in normalized_sql
                ):
                    run_id = parameters[-2]
                    persisted_finding = await database.fetch_one(
                        "SELECT status FROM watcher_findings WHERE run_id = ?",
                        (run_id,),
                    )
                    assert persisted_finding == {"status": "OPEN"}
                    completion_failure_injected = True
                    raise RuntimeError("simulated run completion failure")
                return await original_execute(sql, parameters)

            monkeypatch.setattr(database, "execute", fail_run_completion)
            response = await client.post(
                f"/admin/events/{event_id}/watcher-check",
                headers=headers,
            )

            assert response.status_code == 502, response.text
            assert completion_failure_injected is True
            failed_run_id = response.json()["detail"]["run_id"]
            runs_response = await client.get(
                "/admin/watcher/runs",
                headers=headers,
                params={"status": "FAILED"},
            )
            findings_response = await client.get(
                "/admin/watcher/findings",
                headers=headers,
                params={"status": "OPEN"},
            )

        assert runs_response.status_code == 200, runs_response.text
        failed_runs = runs_response.json()["runs"]
        assert any(run["id"] == failed_run_id for run in failed_runs)
        assert findings_response.status_code == 200, findings_response.text
        open_findings = findings_response.json()["findings"]
        assert all(finding["run_id"] != failed_run_id for finding in open_findings)
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_watcher_policy_sanitizes_model_output_and_findings(tmp_path, monkeypatch):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    fake_secret = "sk-FAKE-WATCHER-POLICY-123456789"
    private_prompt = "private policy system instructions"
    private_path = r"C:\private\uploads\watcher-policy.json"
    now = time.time()
    await database.execute(
        """
        INSERT INTO tasks (
            id, business_id, venue_id, session_id, description, status,
            error, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'FAILED', ?, ?, ?)
        """,
        (
            "task-policy-sanitized",
            "RW-POLICY-SANITIZED",
            "venue-alpha",
            "session-policy-sanitized",
            "review incomplete follow-up",
            (
                "recipient unavailable; "
                f"api_key={fake_secret}; file_path={private_path}"
            ),
            now,
            now,
        ),
    )
    observed_context = {}

    async def successful_watcher(self, context, trace_id):
        observed_context.update(context)
        return SkillOutput(
            success=True,
            reply_text=f"Policy audit complete; api_key={fake_secret}",
            structured_data={
                "is_violation_found": True,
                "escalated_cases": [
                    {
                        "case_id": "case-policy-sanitized",
                        "source_type": "event",
                        "issue_type": "SLA_EXCEEDED",
                        "violation_reason": (
                            "Business follow-up is incomplete; "
                            f"api_key={fake_secret}; file_path={private_path}"
                        ),
                        "severity_level": "P1",
                    }
                ],
                "business_summary": "one follow-up requires review",
                "raw_prompt": private_prompt,
                "artifact": {"local_path": private_path},
            },
        )

    monkeypatch.setattr(
        "src.memory_palace.core.watcher_runtime.WatcherSkill.run",
        successful_watcher,
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
            created = await client.post(
                "/admin/watcher/policies",
                headers=headers,
                json={
                    "name": "Policy output sanitization",
                    "schedule_cron": "0 10 * * *",
                    "enabled": True,
                    "check_types": ["TASK"],
                },
            )
            assert created.status_code == 201, created.text
            response = await client.post(
                f"/admin/watcher/policies/{created.json()['policy']['id']}/run",
                headers=headers,
            )

        assert response.status_code == 200, response.text
        body = response.json()
        persisted = await database.fetch_one(
            "SELECT summary, result_json FROM watcher_runs WHERE id = ?",
            (body["run_id"],),
        )
        finding = await database.fetch_one(
            "SELECT title, description FROM watcher_findings WHERE run_id = ?",
            (body["run_id"],),
        )
        serialized_public_data = json.dumps(
            {
                "watcher_context": observed_context,
                "response": body,
                "persisted": persisted,
                "finding": finding,
            },
            ensure_ascii=False,
        )
        assert fake_secret not in serialized_public_data
        assert private_prompt not in serialized_public_data
        assert "watcher-policy.json" not in serialized_public_data
        assert "Policy audit complete" in body["summary"]
        assert "Business follow-up is incomplete" in finding["description"]
        assert "recipient unavailable" in observed_context["audit_target_logs"][0][
            "employee_replies"
        ]
        assert json.loads(persisted["result_json"])["business_summary"] == (
            "one follow-up requires review"
        )
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_watcher_policy_failure_persists_and_logs_only_public_error(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    captured_logs = []
    sink_id = logger.add(lambda message: captured_logs.append(str(message)), level="ERROR")
    raw_failure = (
        "DeepSeek 401 authentication failed; "
        "api_key=sk-FAKE-WATCHER-POLICY-FAILURE-123456789; "
        "prompt=private watcher policy instructions; "
        r"file_path=C:\private\uploads\watcher-policy-failure.json"
    )

    async def failed_watcher(self, context, trace_id):
        return SkillOutput(success=False, error_msg=raw_failure)

    monkeypatch.setattr(
        "src.memory_palace.core.watcher_runtime.WatcherSkill.run",
        failed_watcher,
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
            created = await client.post(
                "/admin/watcher/policies",
                headers=headers,
                json={
                    "name": "Policy failure sanitization",
                    "schedule_cron": "0 10 * * *",
                    "enabled": True,
                    "check_types": ["SLA"],
                },
            )
            response = await client.post(
                f"/admin/watcher/policies/{created.json()['policy']['id']}/run",
                headers=headers,
            )

        assert response.status_code == 502, response.text
        run = await database.fetch_one(
            "SELECT status, error FROM watcher_runs WHERE policy_id = ? ORDER BY started_at DESC LIMIT 1",
            (created.json()["policy"]["id"],),
        )
        assert run["status"] == "FAILED"
        assert run["error"] == public_error_message(raw_failure, context="operation")
        captured_error_log = "".join(captured_logs)
        assert "RuntimeError" in captured_error_log
        assert "sk-FAKE-WATCHER-POLICY-FAILURE" not in captured_error_log
        assert "private watcher policy instructions" not in captured_error_log
        assert "watcher-policy-failure.json" not in captured_error_log
    finally:
        logger.remove(sink_id)
        await database.close()


@pytest.mark.asyncio
async def test_watcher_policy_removes_open_finding_when_run_completion_fails(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)

    async def watcher_with_issue(self, context, trace_id):
        return SkillOutput(
            success=True,
            structured_data={
                "is_violation_found": True,
                "escalated_cases": [
                    {
                        "case_id": "case-policy-post-persist-failure",
                        "source_type": "event",
                        "issue_type": "SLA_EXCEEDED",
                        "violation_reason": "Business follow-up is overdue.",
                        "severity_level": "P1",
                    }
                ],
            },
        )

    monkeypatch.setattr(
        "src.memory_palace.core.watcher_runtime.WatcherSkill.run",
        watcher_with_issue,
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
            created = await client.post(
                "/admin/watcher/policies",
                headers=headers,
                json={
                    "name": "Policy post-persist failure",
                    "schedule_cron": "0 10 * * *",
                    "enabled": True,
                    "check_types": ["SLA"],
                },
            )
            assert created.status_code == 201, created.text
            policy_id = created.json()["policy"]["id"]
            original_execute = database.execute
            completion_failure_injected = False

            async def fail_run_completion(sql, parameters=()):
                nonlocal completion_failure_injected
                normalized_sql = " ".join(sql.split())
                if (
                    not completion_failure_injected
                    and "UPDATE watcher_runs SET status = 'SUCCEEDED'" in normalized_sql
                ):
                    run_id = parameters[-2]
                    persisted_finding = await database.fetch_one(
                        "SELECT status FROM watcher_findings WHERE run_id = ?",
                        (run_id,),
                    )
                    assert persisted_finding == {"status": "OPEN"}
                    completion_failure_injected = True
                    raise RuntimeError("simulated run completion failure")
                return await original_execute(sql, parameters)

            monkeypatch.setattr(database, "execute", fail_run_completion)
            response = await client.post(
                f"/admin/watcher/policies/{policy_id}/run",
                headers=headers,
            )

            assert response.status_code == 502, response.text
            assert completion_failure_injected is True
            runs_response = await client.get(
                "/admin/watcher/runs",
                headers=headers,
                params={"status": "FAILED"},
            )
            assert runs_response.status_code == 200, runs_response.text
            failed_run = next(
                run
                for run in runs_response.json()["runs"]
                if run["policy_id"] == policy_id
            )
            findings_response = await client.get(
                "/admin/watcher/findings",
                headers=headers,
                params={"status": "OPEN"},
            )

        assert findings_response.status_code == 200, findings_response.text
        open_findings = findings_response.json()["findings"]
        assert all(finding["run_id"] != failed_run["id"] for finding in open_findings)
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_event_watcher_check_reuses_open_finding_but_keeps_every_run(tmp_path, monkeypatch):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    event_id = await _seed_complete_event(database, event_id="event-watcher-finding")

    async def watcher_with_issue(self, context, trace_id):
        return SkillOutput(
            success=True,
            reply_text="发现通知回执需要复核。",
            structured_data={
                "is_violation_found": True,
                "escalated_cases": [
                    {
                        "case_id": event_id,
                        "source_type": "event",
                        "issue_type": "DELIVERY_EVIDENCE",
                        "violation_reason": "恢复通知只有发送记录，缺少接收方确认回执。",
                        "severity_level": "P2",
                    }
                ],
                "audit_score": 90,
            },
            action_taken="sop_compliance_audit",
        )

    monkeypatch.setattr(
        "src.memory_palace.core.watcher_runtime.WatcherSkill.run",
        watcher_with_issue,
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
            first = await client.post(
                f"/admin/events/{event_id}/watcher-check",
                headers=headers,
            )
            second = await client.post(
                f"/admin/events/{event_id}/watcher-check",
                headers=headers,
            )

        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        first_body = first.json()
        second_body = second.json()
        assert first_body["ready_to_close"] is False
        assert "缺少接收方确认回执" in first_body["summary"]
        assert first_body["run"]["id"] != second_body["run"]["id"]
        assert first_body["findings"][0]["id"] == second_body["findings"][0]["id"]
        assert first_body["findings"][0]["reused"] is False
        assert second_body["findings"][0]["reused"] is True
        assert first_body["findings"][0]["issue_fingerprint"]

        runs = await database.fetch_all(
            "SELECT id, status, finding_count FROM watcher_runs WHERE event_id = ?",
            (event_id,),
        )
        assert len(runs) == 2
        assert all(run["status"] == "SUCCEEDED" for run in runs)
        assert all(run["finding_count"] == 1 for run in runs)
        findings = await database.fetch_all(
            """
            SELECT * FROM watcher_findings
            WHERE venue_id = 'venue-alpha' AND event_id = ? AND status != 'CLOSED'
            """,
            (event_id,),
        )
        assert len(findings) == 1
        assert findings[0]["run_id"] == first_body["run"]["id"]
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_event_watcher_check_enforces_roles_and_strict_tenant_scope(tmp_path, monkeypatch):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    event_id = await _seed_complete_event(database, event_id="event-watcher-tenant-alpha")

    async def successful_watcher(self, context, trace_id):
        return SkillOutput(
            success=True,
            structured_data={
                "is_violation_found": False,
                "escalated_cases": [],
                "audit_score": 100,
            },
        )

    monkeypatch.setattr(
        "src.memory_palace.core.watcher_runtime.WatcherSkill.run",
        successful_watcher,
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
            await create_user(client, admin_headers, username="watcher-manager", role="manager")
            await create_user(client, admin_headers, username="watcher-operator", role="operator")
            manager_headers = await login(client, "watcher-manager", "Strong-Password-2026")
            operator_headers = await login(client, "watcher-operator", "Strong-Password-2026")

            manager_response = await client.post(
                f"/admin/events/{event_id}/watcher-check",
                headers=manager_headers,
            )
            operator_response = await client.post(
                f"/admin/events/{event_id}/watcher-check",
                headers=operator_headers,
            )

            now = time.time()
            await database.execute(
                """
                INSERT INTO venues (id, name, status, created_at, updated_at)
                VALUES ('venue-beta', '南麓游客中心', 'ACTIVE', ?, ?)
                """,
                (now, now),
            )
            await database.execute(
                """
                INSERT INTO confirmed_events (
                    event_id, business_id, from_user, raw_text, event_type,
                    severity, memory_content, created_at, venue_id, status
                ) VALUES ('event-watcher-tenant-beta', 'SJ-BETA-WATCHER',
                    'beta-user', '南麓事件', '设备故障', 'P3', '南麓事件', ?,
                    'venue-beta', 'OPEN')
                """,
                (now,),
            )
            cross_tenant_response = await client.post(
                "/admin/events/event-watcher-tenant-beta/watcher-check",
                headers=admin_headers,
            )

        assert manager_response.status_code == 200, manager_response.text
        assert operator_response.status_code == 403, operator_response.text
        assert operator_response.json()["detail"]["code"] == "AUTH_FORBIDDEN"
        assert cross_tenant_response.status_code == 404, cross_tenant_response.text
        assert cross_tenant_response.json()["detail"]["code"] == "EVENT_NOT_FOUND"
        assert await database.fetch_all(
            "SELECT id FROM watcher_runs WHERE venue_id = 'venue-beta'",
        ) == []
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_event_watcher_check_surfaces_deterministic_closure_blockers(tmp_path, monkeypatch):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    event_id = await _seed_complete_event(database, event_id="event-watcher-blocked")
    await database.execute(
        "UPDATE tasks SET status = 'RUNNING' WHERE event_id = ?",
        (event_id,),
    )
    await database.execute(
        """
        UPDATE approval_requests
        SET status = 'PENDING', execution_status = 'NOT_STARTED'
        WHERE event_id = ?
        """,
        (event_id,),
    )
    await database.execute(
        """
        UPDATE push_logs SET delivery_status = 'FAILED', delivery_error = '接收方不可达'
        WHERE trace_id = 'trace-notification-watcher-ready'
        """,
    )

    async def watcher_without_model_issues(self, context, trace_id):
        return SkillOutput(
            success=True,
            structured_data={
                "is_violation_found": False,
                "escalated_cases": [],
                "audit_score": 100,
            },
        )

    monkeypatch.setattr(
        "src.memory_palace.core.watcher_runtime.WatcherSkill.run",
        watcher_without_model_issues,
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
            response = await client.post(
                f"/admin/events/{event_id}/watcher-check",
                headers=headers,
            )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["ready_to_close"] is False
        finding_types = {finding["finding_type"] for finding in body["findings"]}
        assert {
            "UNFINISHED_TASK",
            "PENDING_APPROVAL",
            "NOTIFICATION_DELIVERY_INCOMPLETE",
        }.issubset(finding_types)
        assert "接收方不可达" in body["summary"]
    finally:
        await database.close()
