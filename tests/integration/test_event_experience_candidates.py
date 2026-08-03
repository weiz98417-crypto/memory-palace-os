import json
import time

import pytest

from src.memory_palace.core.event_experience_candidates import (
    EventExperienceCandidateError,
    ensure_event_experience_candidate,
)
from src.memory_palace.knowledge.db_client import AsyncDBClient
from src.memory_palace.knowledge.db_init import init_database
from src.memory_palace.knowledge.experience_schema import init_experience_schema
from src.memory_palace.tools.llm_wrapper import REQUIRED_GENERATIVE_MODEL


EVENT_RESOLUTION = (
    "已更换防松螺栓并校正右后轮防尘护板，完成空载低速三轮试车，"
    "确认无异响、无制动跑偏且温度正常。"
)


class RecordingCandidateExtractor:
    model_name = REQUIRED_GENERATIVE_MODEL

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def extract(self, evidence, *, trace_id: str, venue_id: str):
        self.calls.append(
            {
                "evidence": evidence,
                "trace_id": trace_id,
                "venue_id": venue_id,
            }
        )
        return {
            "title": "雨后观光车轮端间歇性异响处置",
            "applicable_context": "观光车淋雨后出现随轮速变化的金属擦声",
            "signals": ["异响随轮速变化", "无发热和制动跑偏"],
            "decision_rule": "先隔离车辆并检查护板间隙，再决定是否空载试车",
            "recommended_actions": ["停车断电", "检查护板", "空载低速试车"],
            "rationale": "雨后变形的护板可能与制动盘间歇摩擦",
            "prohibitions": ["存在发热、焦味或制动跑偏时禁止继续试车"],
            "exceptions": ["制动异常时升级拖车检修"],
            "source_excerpts": [EVENT_RESOLUTION],
        }


class RetryableCandidateExtractor(RecordingCandidateExtractor):
    def __init__(self) -> None:
        super().__init__()
        self.fail_next = True

    async def extract(self, evidence, *, trace_id: str, venue_id: str):
        self.calls.append(
            {
                "evidence": evidence,
                "trace_id": trace_id,
                "venue_id": venue_id,
            }
        )
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("DeepSeek 暂时不可用")
        return {
            "title": "雨后观光车轮端间歇性异响处置",
            "applicable_context": "观光车淋雨后出现随轮速变化的金属擦声",
            "signals": ["异响随轮速变化", "无发热和制动跑偏"],
            "decision_rule": "先隔离车辆并检查护板间隙，再决定是否空载试车",
            "recommended_actions": ["停车断电", "检查护板", "空载低速试车"],
            "rationale": "雨后变形的护板可能与制动盘间歇摩擦",
            "prohibitions": ["存在发热、焦味或制动跑偏时禁止继续试车"],
            "exceptions": ["制动异常时升级拖车检修"],
            "source_excerpts": [EVENT_RESOLUTION],
        }


async def _database(tmp_path):
    database = AsyncDBClient(tmp_path / "event-experience-candidates.db")
    await init_database(database)
    await init_experience_schema(database)
    return database


async def _seed_closed_event_evidence(database, *, venue_id: str, event_id: str) -> None:
    now = time.time()
    await database.execute(
        """
        INSERT INTO confirmed_events (
            event_id, business_id, from_user, raw_text, event_type, severity,
            context_trigger_data, memory_content, venue_id, source_type,
            status, resolution, trace_id, created_at, confirmed_at, closed_at,
            updated_at
        ) VALUES (?, ?, 'employee-a', ?, '车辆设备故障', 'P2', '{}', ?, ?,
                  'LIVE', 'CLOSED', ?, 'trace-event-source', ?, ?, ?, ?)
        """,
        (
            event_id,
            "SJ-20260730-CAND0001",
            "雨后观光车右后轮出现间歇性金属摩擦声。",
            "[P2] 车辆设备故障：雨后观光车右后轮出现间歇性金属摩擦声。",
            venue_id,
            EVENT_RESOLUTION,
            now - 600,
            now - 590,
            now,
            now,
        ),
    )
    await database.execute(
        """
        INSERT INTO sessions (
            session_id, user_id, venue_id, stage, created_at, updated_at
        ) VALUES ('session-candidate', 'employee-a', ?, 'ACTIVE', ?, ?)
        """,
        (venue_id, now, now),
    )
    await database.execute(
        """
        INSERT INTO tasks (
            id, business_id, venue_id, session_id, event_id, description,
            status, dependencies, evidence_refs_json, result, created_at,
            updated_at, completed_at
        ) VALUES ('task-candidate', 'RW-20260730-CAND0001', ?,
                  'session-candidate', ?, '更换螺栓并完成空载试车', 'DONE',
                  '[]', ?, ?, ?, ?, ?)
        """,
        (
            venue_id,
            event_id,
            json.dumps([{"type": "photo", "name": "试车记录"}], ensure_ascii=False),
            json.dumps({"summary": "三轮试车无异响且温度正常"}, ensure_ascii=False),
            now - 300,
            now - 120,
            now - 120,
        ),
    )
    await database.execute(
        """
        INSERT INTO approval_requests (
            approval_id, business_id, venue_id, tool_name, args, session_id,
            event_id, task_id, user_id, requested_at, requested_by, status,
            reviewed_at, reviewed_by, comment, execution_status,
            execution_result, evidence_snapshot_json
        ) VALUES ('approval-candidate', 'SP-20260730-CAND0001', ?,
                  'send_in_app_alert', ?, 'session-candidate', ?,
                  'task-candidate', 'manager-a', ?, 'manager-a', 'APPROVED', ?,
                  'manager-a', '同意启用备用车', 'SUCCEEDED', ?, ?)
        """,
        (
            venue_id,
            json.dumps({"message": "启用备用车"}, ensure_ascii=False),
            event_id,
            now - 240,
            now - 220,
            json.dumps({"delivery_status": "DELIVERED"}, ensure_ascii=False),
            json.dumps({"task_result": "备用车已交接"}, ensure_ascii=False),
        ),
    )
    await database.execute(
        """
        INSERT INTO watcher_policies (
            id, venue_id, name, description, schedule_cron, enabled,
            check_types_json, config_json, version, created_by, created_at,
            updated_at
        ) VALUES ('policy-candidate', ?, '事件闭环检查', '', '0 10 * * *', 1,
                  '["EVENT"]', '{}', 1, 'manager-a', ?, ?)
        """,
        (venue_id, now - 1000, now - 1000),
    )
    await database.execute(
        """
        INSERT INTO watcher_runs (
            id, policy_id, venue_id, trigger_source, status, trace_id,
            target_count, finding_count, summary, result_json, started_at,
            completed_at
        ) VALUES ('watcher-run-candidate', 'policy-candidate', ?, ?, 'SUCCEEDED',
                  'trace-watcher-candidate', 1, 0, '证据完整，可闭环', ?, ?, ?)
        """,
        (
            venue_id,
            f"EVENT:{event_id}",
            json.dumps(
                {
                    "event_id": event_id,
                    "ready_to_close": True,
                    "checked_items": ["任务结果", "审批执行", "通知送达"],
                },
                ensure_ascii=False,
            ),
            now - 90,
            now - 60,
        ),
    )


@pytest.mark.asyncio
async def test_closed_event_creates_one_unindexed_candidate_with_complete_evidence(tmp_path):
    database = await _database(tmp_path)
    extractor = RecordingCandidateExtractor()
    venue_id = "venue-alpha"
    event_id = "event-candidate-success"
    principal = {"venue_id": venue_id, "user_id": "manager-a"}
    await _seed_closed_event_evidence(database, venue_id=venue_id, event_id=event_id)

    try:
        created = await ensure_event_experience_candidate(
            database,
            venue_id=venue_id,
            event_id=event_id,
            trace_id="trace-candidate-create",
            principal=principal,
            extractor=extractor,
        )
        replayed = await ensure_event_experience_candidate(
            database,
            venue_id=venue_id,
            event_id=event_id,
            trace_id="trace-candidate-replay",
            principal=principal,
            extractor=extractor,
        )

        assert created["outcome"] == "CREATED"
        assert replayed["outcome"] == "REPLAYED"
        assert replayed["idempotent_replay"] is True
        assert len(extractor.calls) == 1

        candidate = created["candidate"]
        assert candidate["source_event_id"] == event_id
        assert candidate["status"] == "DRAFT"
        assert candidate["index_status"] == "NOT_INDEXED"
        assert candidate["extraction_status"] == "SUCCEEDED"
        assert candidate["extraction_model"] == REQUIRED_GENERATIVE_MODEL
        assert candidate["task_results_snapshot"][0]["result"]["summary"] == "三轮试车无异响且温度正常"
        assert candidate["approval_evidence_snapshot"][0]["evidence_snapshot"]["task_result"] == "备用车已交接"
        assert candidate["watcher_evidence_snapshot"]["run"]["summary"] == "证据完整，可闭环"
        assert candidate["watcher_evidence_snapshot"]["run"]["result"]["ready_to_close"] is True

        candidate_count = await database.fetch_one(
            "SELECT COUNT(*) AS count FROM experience_candidates WHERE venue_id = ? AND source_event_id = ?",
            (venue_id, event_id),
        )
        card_count = await database.fetch_one(
            "SELECT COUNT(*) AS count FROM experience_cards WHERE venue_id = ?",
            (venue_id,),
        )
        attempt_count = await database.fetch_one(
            "SELECT COUNT(*) AS count FROM experience_candidate_attempts WHERE venue_id = ? AND candidate_id = ?",
            (venue_id, candidate["id"]),
        )
        activity_count = await database.fetch_one(
            """
            SELECT COUNT(*) AS count FROM event_activities
            WHERE venue_id = ? AND event_id = ?
              AND activity_type = 'EXPERIENCE_CANDIDATE_CREATED'
            """,
            (venue_id, event_id),
        )
        audit_count = await database.fetch_one(
            """
            SELECT COUNT(*) AS count FROM audit_logs
            WHERE venue_id = ? AND action = 'EXPERIENCE_CANDIDATE_CREATED'
              AND resource_type = 'experience_candidate' AND resource_id = ?
            """,
            (venue_id, candidate["id"]),
        )
        assert candidate_count["count"] == 1
        assert card_count["count"] == 0
        assert attempt_count["count"] == 1
        assert activity_count["count"] == 1
        assert audit_count["count"] == 1
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_failed_candidate_extraction_is_retryable_without_publishing_pollution(tmp_path):
    database = await _database(tmp_path)
    extractor = RetryableCandidateExtractor()
    venue_id = "venue-alpha"
    event_id = "event-candidate-retry"
    principal = {"venue_id": venue_id, "user_id": "manager-a"}
    await _seed_closed_event_evidence(database, venue_id=venue_id, event_id=event_id)

    try:
        failed = await ensure_event_experience_candidate(
            database,
            venue_id=venue_id,
            event_id=event_id,
            trace_id="trace-candidate-failed",
            principal=principal,
            extractor=extractor,
        )

        assert failed["outcome"] == "FAILED"
        assert failed["retryable"] is True
        assert failed["candidate"]["status"] == "DRAFT"
        assert failed["candidate"]["index_status"] == "NOT_INDEXED"
        assert failed["candidate"]["extraction_status"] == "FAILED"
        assert failed["candidate"]["attempt_count"] == 1
        assert "DeepSeek 暂时不可用" in failed["extraction"]["error"]
        assert await database.fetch_one(
            "SELECT id FROM experience_cards WHERE venue_id = ?",
            (venue_id,),
        ) is None
        assert await database.fetch_one(
            """
            SELECT id FROM event_activities
            WHERE venue_id = ? AND event_id = ?
              AND activity_type = 'EXPERIENCE_CANDIDATE_CREATED'
            """,
            (venue_id, event_id),
        ) is None

        recovered = await ensure_event_experience_candidate(
            database,
            venue_id=venue_id,
            event_id=event_id,
            trace_id="trace-candidate-failed",
            principal=principal,
            extractor=extractor,
        )

        assert recovered["outcome"] == "CREATED"
        assert recovered["retryable"] is False
        assert recovered["candidate"]["extraction_status"] == "SUCCEEDED"
        assert recovered["candidate"]["attempt_count"] == 2
        assert recovered["candidate"]["extraction_trace_id"] == "trace-candidate-failed"
        assert len(extractor.calls) == 2

        attempts = await database.fetch_all(
            """
            SELECT attempt_number, trace_id, model_name, status, error
            FROM experience_candidate_attempts
            WHERE venue_id = ? AND candidate_id = ?
            ORDER BY attempt_number
            """,
            (venue_id, recovered["candidate"]["id"]),
        )
        assert [(attempt["attempt_number"], attempt["status"]) for attempt in attempts] == [
            (1, "FAILED"),
            (2, "SUCCEEDED"),
        ]
        assert {attempt["model_name"] for attempt in attempts} == {
            REQUIRED_GENERATIVE_MODEL
        }
        assert attempts[0]["trace_id"] == "trace-candidate-failed"
        assert attempts[1]["trace_id"] == "trace-candidate-failed"
        assert "DeepSeek 暂时不可用" in attempts[0]["error"]

        candidate_count = await database.fetch_one(
            "SELECT COUNT(*) AS count FROM experience_candidates WHERE venue_id = ? AND source_event_id = ?",
            (venue_id, event_id),
        )
        assert candidate_count["count"] == 1
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_event_candidate_generation_is_tenant_isolated_before_model_invocation(tmp_path):
    database = await _database(tmp_path)
    extractor = RecordingCandidateExtractor()
    event_id = "event-candidate-tenant"
    await _seed_closed_event_evidence(
        database,
        venue_id="venue-alpha",
        event_id=event_id,
    )

    try:
        with pytest.raises(EventExperienceCandidateError, match="当前场地不存在"):
            await ensure_event_experience_candidate(
                database,
                venue_id="venue-other",
                event_id=event_id,
                trace_id="trace-candidate-cross-tenant",
                principal={"venue_id": "venue-other", "user_id": "manager-other"},
                extractor=extractor,
            )

        with pytest.raises(EventExperienceCandidateError, match="不属于同一场地"):
            await ensure_event_experience_candidate(
                database,
                venue_id="venue-alpha",
                event_id=event_id,
                trace_id="trace-candidate-principal-mismatch",
                principal={"venue_id": "venue-other", "user_id": "manager-other"},
                extractor=extractor,
            )

        assert extractor.calls == []
        assert await database.fetch_one(
            "SELECT id FROM experience_candidates WHERE source_event_id = ?",
            (event_id,),
        ) is None
    finally:
        await database.close()
