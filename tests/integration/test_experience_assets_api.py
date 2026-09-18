import asyncio
import json
import time
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi import FastAPI

from src.memory_palace.api.auth import require_auth
from src.memory_palace.api.v1.endpoints.experiences import admin_router, assistant_router
from src.memory_palace.api.v1.endpoints.management import router as management_router
from src.memory_palace.core.experience_assets import ExperienceDraftExtractionError
from src.memory_palace.knowledge.db_client import AsyncDBClient
from src.memory_palace.knowledge.db_init import init_database
from src.memory_palace.knowledge.experience_schema import init_experience_schema


WORKFLOW_ANSWERS = (
    "异响随轮速变化，踩刹车时不变大。",
    "先停车断电并检查护板间隙，再决定是否空载试车。",
    "发热、焦味、制动跑偏或轴承松旷时必须停止试车并拖车检修。",
    "适用于悦山景区观光车检修岗位，不适用于载客试车。",
)


class RecordingVectorStore:
    def __init__(self):
        self.documents = {}
        self.fail_next_upsert = False

    def upsert_experience(self, content, metadata, doc_id, strict=False):
        if self.fail_next_upsert:
            self.fail_next_upsert = False
            raise RuntimeError("vector write failed")
        self.documents[doc_id] = {"content": content, "metadata": dict(metadata)}
        return True

    def delete_experience(self, doc_id, strict=False):
        self.documents.pop(doc_id, None)
        return True

    def query_experience(self, text, top_k=5, threshold=0.0, venue_id=None, strict=False):
        return [
            {"id": doc_id, "content": item["content"], "metadata": item["metadata"], "score": 0.91}
            for doc_id, item in self.documents.items()
            if item["metadata"].get("venue_id") == venue_id
        ][:top_k]


class RecordingExperienceExtractor:
    def __init__(self):
        self.calls = []

    async def extract(self, evidence, *, trace_id, venue_id):
        self.calls.append(
            {
                "evidence": evidence,
                "trace_id": trace_id,
                "venue_id": venue_id,
            }
        )
        return {
            "title": "雨后观光车轮端间歇性金属异响判断",
            "applicable_context": "观光车淋雨后出现随轮速变化的轻微金属擦声",
            "signals": ["异响随轮速变化", "踩刹车时声音不增大", "无发热和焦味"],
            "decision_rule": "先停车隔离，检查防尘护板间隙，再决定是否进行空载试车",
            "recommended_actions": ["停车断电", "检查护板间隙", "空载低速试车"],
            "rationale": "雨后护板轻微变形可能与制动盘间歇摩擦",
            "prohibitions": ["存在发热、焦味或制动跑偏时禁止继续试车"],
            "exceptions": ["轴承松旷或制动异常应升级拖车检修"],
            "source_excerpts": ["发热、焦味、制动跑偏或轴承松旷时必须停止试车并拖车检修。"],
        }


class FailingExperienceExtractor:
    async def extract(self, evidence, *, trace_id, venue_id):
        raise ExperienceDraftExtractionError("DeepSeek 暂时不可用")


async def _build_app(tmp_path):
    db = AsyncDBClient(tmp_path / "experience-assets.db")
    await init_database(db)
    await init_experience_schema(db)
    now = time.time()
    for venue_id, venue_name in (("venue-yueshan", "悦山景区"), ("venue-other", "其他景区")):
        await db.execute(
            "INSERT INTO venues (id, name, status, created_at, updated_at) VALUES (?, ?, 'ACTIVE', ?, ?)",
            (venue_id, venue_name, now, now),
        )
    users = (
        ("admin-yueshan", "admin-yueshan", "刘海", "admin", "venue-yueshan"),
        ("manager-yueshan", "manager-yueshan", "赵敏", "manager", "venue-yueshan"),
        ("expert-yueshan", "expert-yueshan", "张建国", "operator", "venue-yueshan"),
        ("operator-yueshan", "operator-yueshan", "周琪", "operator", "venue-yueshan"),
        ("unbound-yueshan", "unbound-yueshan", "未绑定员工", "operator", "venue-yueshan"),
        ("inactive-yueshan", "inactive-yueshan", "停用员工", "operator", "venue-yueshan"),
        ("admin-other", "admin-other", "其他管理员", "admin", "venue-other"),
        ("expert-other", "expert-other", "其他景区专家", "operator", "venue-other"),
    )
    for user_id, username, display_name, role, venue_id in users:
        await db.execute(
            """
            INSERT INTO users (
                id, username, password_hash, display_name, role, venue_id,
                status, created_at, updated_at
            ) VALUES (?, ?, 'test-hash', ?, ?, ?, 'ACTIVE', ?, ?)
            """,
            (user_id, username, display_name, role, venue_id, now, now),
        )
    await db.execute(
        "UPDATE users SET status = 'DISABLED' WHERE id = ?",
        ("inactive-yueshan",),
    )
    for identity_id, venue_id, tenant_id, external_user_id, user_id in (
        (
            "identity-expert-yueshan",
            "venue-yueshan",
            "corp-yueshan",
            "wecom-expert-yueshan",
            "expert-yueshan",
        ),
        (
            "identity-inactive-yueshan",
            "venue-yueshan",
            "corp-yueshan",
            "wecom-inactive-yueshan",
            "inactive-yueshan",
        ),
        (
            "identity-expert-other",
            "venue-other",
            "corp-other",
            "wecom-expert-other",
            "expert-other",
        ),
    ):
        await db.execute(
            """
            INSERT INTO channel_identities (
                id, venue_id, channel, external_tenant_id, external_user_id,
                user_id, status, created_at, updated_at
            ) VALUES (?, ?, 'WECOM_SIMULATOR', ?, ?, ?, 'ACTIVE', ?, ?)
            """,
            (
                identity_id,
                venue_id,
                tenant_id,
                external_user_id,
                user_id,
                now,
                now,
            ),
        )

    app = FastAPI()
    app.state.db_client = db
    app.state.vector_store = RecordingVectorStore()
    app.state.experience_draft_extractor = RecordingExperienceExtractor()
    app.state.test_principal = {
        "user_id": "manager-yueshan",
        "username": "manager-yueshan",
        "role": "manager",
        "venue_id": "venue-yueshan",
        "auth_type": "test",
    }

    async def authenticated_principal():
        return app.state.test_principal

    app.dependency_overrides[require_auth] = authenticated_principal
    app.include_router(admin_router, prefix="/api/v1/admin")
    app.include_router(management_router, prefix="/api/v1/admin")
    app.include_router(assistant_router, prefix="/api/v1/assistant")
    return app, db


def _set_principal(app, *, user_id, role="operator", venue_id="venue-yueshan"):
    app.state.test_principal = {
        "user_id": user_id,
        "username": user_id,
        "role": role,
        "venue_id": venue_id,
        "auth_type": "test",
    }


def _synchronize_next_transactions(db, parties=2):
    original_transaction = db.transaction
    ready = asyncio.Event()
    arrivals = 0

    @asynccontextmanager
    async def synchronized_transaction():
        nonlocal arrivals
        arrivals += 1
        if arrivals >= parties:
            ready.set()
        await ready.wait()
        async with original_transaction() as transaction:
            yield transaction

    db.transaction = synchronized_transaction
    return original_transaction


async def _create_authorized_expert_and_interview(client):
    expert_response = await client.post(
        "/api/v1/admin/experts",
        json={
            "user_id": "expert-yueshan",
            "display_name": "张建国",
            "job_title": "资深设备主管",
            "department": "设备运营部",
            "years_experience": 18,
            "expertise": ["观光车", "雨后复运"],
            "authorization_status": "SIGNED",
            "authorization_statement": "本人同意将确认后的经验用于悦山景区组织知识服务。",
        },
    )
    assert expert_response.status_code == 201, expert_response.text
    expert = expert_response.json()["expert"]
    interview_response = await client.post(
        "/api/v1/admin/experience-interviews",
        json={
            "expert_id": expert["id"],
            "title": "雨后观光车轮端异响判断",
            "source_event_id": "SJ-ACTING-001",
            "authorization_scopes": [
                {"scope_type": "VENUE", "scope_value": "venue-yueshan"}
            ],
        },
    )
    assert interview_response.status_code == 201, interview_response.text
    return expert, interview_response.json()["interview"]


async def _answer_all_questions(client, interview_id, key_prefix):
    interview_url = f"/api/v1/assistant/experience/interviews/{interview_id}"
    for index, answer in enumerate(WORKFLOW_ANSWERS, start=1):
        response = await client.post(
            f"{interview_url}/answers",
            headers={"Idempotency-Key": f"{key_prefix}-{index}"},
            json={"answer": answer},
        )
        assert response.status_code == 200, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("actor_user_id", "actor_role"),
    (("manager-yueshan", "manager"), ("admin-yueshan", "admin")),
)
async def test_management_roles_can_view_bound_employee_experience_home(
    tmp_path,
    actor_user_id,
    actor_role,
):
    app, db = await _build_app(tmp_path)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            expert, _ = await _create_authorized_expert_and_interview(client)
            _set_principal(app, user_id=actor_user_id, role=actor_role)
            response = await client.get(
                "/api/v1/assistant/experience",
                params={"acting_user_id": "expert-yueshan"},
                headers={"X-Trace-ID": f"acting-home-{actor_role}"},
            )

        assert response.status_code == 200, response.text
        assert response.json()["expert"]["id"] == expert["id"]
        assert len(response.json()["interviews"]) == 1
        audit = await db.fetch_one(
            """
            SELECT user_id, outcome, metadata_json FROM audit_logs
            WHERE action = 'EXPERIENCE_ACTING_IDENTITY_USED' AND trace_id = ?
            """,
            (f"acting-home-{actor_role}",),
        )
        assert audit is not None
        assert audit["user_id"] == actor_user_id
        assert audit["outcome"] == "SUCCEEDED"
        assert json.loads(audit["metadata_json"])["acting_user_id"] == "expert-yueshan"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_acting_employee_identity_rejects_impersonation_and_tenant_escape(
    tmp_path,
):
    app, db = await _build_app(tmp_path)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await _create_authorized_expert_and_interview(client)

            _set_principal(app, user_id="operator-yueshan")
            impersonation = await client.get(
                "/api/v1/assistant/experience",
                params={"acting_user_id": "expert-yueshan"},
            )

            _set_principal(app, user_id="manager-yueshan", role="manager")
            cross_tenant = await client.get(
                "/api/v1/assistant/experience",
                params={"acting_user_id": "expert-other"},
            )
            unbound = await client.get(
                "/api/v1/assistant/experience",
                params={"acting_user_id": "unbound-yueshan"},
            )
            inactive = await client.get(
                "/api/v1/assistant/experience",
                params={"acting_user_id": "inactive-yueshan"},
            )

            _set_principal(app, user_id="expert-yueshan")
            unchanged = await client.get("/api/v1/assistant/experience")

        assert impersonation.status_code == 403, impersonation.text
        assert impersonation.json()["detail"]["code"] == "EXPERIENCE_ACTING_IDENTITY_FORBIDDEN"
        for response in (cross_tenant, unbound, inactive):
            assert response.status_code == 404, response.text
            assert response.json()["detail"]["code"] == "EXPERIENCE_ACTING_IDENTITY_NOT_FOUND"
        assert unchanged.status_code == 200, unchanged.text
        assert unchanged.json()["expert"]["user_id"] == "expert-yueshan"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_answer_and_interview_progress_are_committed_atomically(tmp_path):
    app, db = await _build_app(tmp_path)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            _, interview = await _create_authorized_expert_and_interview(client)
            _set_principal(app, user_id="expert-yueshan")
            interview_url = f"/api/v1/assistant/experience/interviews/{interview['id']}"
            assert (await client.post(f"{interview_url}/accept")).status_code == 200

            await db.execute(
                """
                CREATE TRIGGER fail_interview_progress
                BEFORE UPDATE OF current_question_index ON experience_interviews
                WHEN NEW.current_question_index > OLD.current_question_index
                BEGIN
                    SELECT RAISE(ABORT, 'forced progress failure');
                END
                """
            )
            failed = await client.post(
                f"{interview_url}/answers",
                headers={"Idempotency-Key": "atomic-answer-1"},
                json={"answer": "先确认异响是否随轮速变化。"},
            )

            assert failed.status_code == 500, failed.text
            assert await db.fetch_one(
                "SELECT id FROM experience_interview_turns WHERE idempotency_key = ?",
                ("atomic-answer-1",),
            ) is None
            unchanged = await db.fetch_one(
                "SELECT status, current_question_index FROM experience_interviews WHERE id = ?",
                (interview["id"],),
            )
            assert unchanged == {"status": "ACCEPTED", "current_question_index": 0}

            await db.execute("DROP TRIGGER fail_interview_progress")
            retried = await client.post(
                f"{interview_url}/answers",
                headers={"Idempotency-Key": "atomic-answer-1"},
                json={"answer": "先确认异响是否随轮速变化。"},
            )

        assert retried.status_code == 200, retried.text
        assert retried.json()["interview"]["progress"]["answered"] == 1
        assert retried.json()["idempotent_replay"] is False
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_blank_interview_answer_does_not_advance_progress(tmp_path):
    app, db = await _build_app(tmp_path)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            _, interview = await _create_authorized_expert_and_interview(client)
            _set_principal(app, user_id="expert-yueshan")
            interview_url = f"/api/v1/assistant/experience/interviews/{interview['id']}"
            assert (await client.post(f"{interview_url}/accept")).status_code == 200

            response = await client.post(
                f"{interview_url}/answers",
                headers={"Idempotency-Key": "blank-answer"},
                json={"answer": "   \t  "},
            )

        assert response.status_code == 422, response.text
        assert response.json()["detail"]["code"] == "INTERVIEW_ANSWER_REQUIRED"
        assert await db.fetch_one(
            "SELECT id FROM experience_interview_turns WHERE interview_id = ?",
            (interview["id"],),
        ) is None
        unchanged = await db.fetch_one(
            "SELECT status, current_question_index FROM experience_interviews WHERE id = ?",
            (interview["id"],),
        )
        assert unchanged == {"status": "ACCEPTED", "current_question_index": 0}
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_completed_interview_assets_are_committed_atomically(tmp_path):
    app, db = await _build_app(tmp_path)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            _, interview = await _create_authorized_expert_and_interview(client)
            _set_principal(app, user_id="expert-yueshan")
            interview_url = f"/api/v1/assistant/experience/interviews/{interview['id']}"
            assert (await client.post(f"{interview_url}/accept")).status_code == 200
            answers = (
                "异响随轮速变化，踩刹车时不变大。",
                "先停车断电并检查护板间隙，再决定是否空载试车。",
                "发热、焦味、制动跑偏或轴承松旷时必须停止试车并拖车检修。",
                "适用于悦山景区观光车检修岗位，不适用于载客试车。",
            )
            for index, answer in enumerate(answers, start=1):
                response = await client.post(
                    f"{interview_url}/answers",
                    headers={"Idempotency-Key": f"atomic-complete-answer-{index}"},
                    json={"answer": answer},
                )
                assert response.status_code == 200, response.text

            await db.execute(
                """
                CREATE TRIGGER fail_experience_version
                BEFORE INSERT ON experience_card_versions
                BEGIN
                    SELECT RAISE(ABORT, 'forced version failure');
                END
                """
            )
            failed = await client.post(
                f"{interview_url}/complete",
                headers={"X-Trace-ID": "atomic-complete-failed"},
            )

            assert failed.status_code == 500, failed.text
            assert await db.fetch_one(
                "SELECT id FROM experience_cards WHERE source_interview_id = ?",
                (interview["id"],),
            ) is None
            assert await db.fetch_one(
                "SELECT id FROM experience_authorizations WHERE card_id IN (SELECT id FROM experience_cards WHERE source_interview_id = ?)",
                (interview["id"],),
            ) is None
            assert await db.fetch_one(
                "SELECT id FROM experience_card_versions WHERE card_id IN (SELECT id FROM experience_cards WHERE source_interview_id = ?)",
                (interview["id"],),
            ) is None
            interview_state = await db.fetch_one(
                "SELECT status, completed_at FROM experience_interviews WHERE id = ?",
                (interview["id"],),
            )
            assert interview_state == {"status": "IN_PROGRESS", "completed_at": None}
            assert await db.fetch_one(
                "SELECT id FROM audit_logs WHERE action = 'EXPERIENCE_DRAFT_CREATED' AND trace_id = ?",
                ("atomic-complete-failed",),
            ) is None

            await db.execute("DROP TRIGGER fail_experience_version")
            retried = await client.post(
                f"{interview_url}/complete",
                headers={"X-Trace-ID": "atomic-complete-retried"},
            )

        assert retried.status_code == 201, retried.text
        assert retried.json()["idempotent_replay"] is False
        assert retried.json()["card"]["status"] == "DRAFT"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_concurrent_same_key_answer_replays_without_duplicate_progress_or_audit(tmp_path):
    app, db = await _build_app(tmp_path)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            _, interview = await _create_authorized_expert_and_interview(client)
            _set_principal(app, user_id="expert-yueshan")
            interview_url = f"/api/v1/assistant/experience/interviews/{interview['id']}"
            assert (await client.post(f"{interview_url}/accept")).status_code == 200

            original_transaction = _synchronize_next_transactions(db)
            try:
                responses = await asyncio.wait_for(
                    asyncio.gather(
                        client.post(
                            f"{interview_url}/answers",
                            headers={"Idempotency-Key": "concurrent-answer-1"},
                            json={"answer": WORKFLOW_ANSWERS[0]},
                        ),
                        client.post(
                            f"{interview_url}/answers",
                            headers={"Idempotency-Key": "concurrent-answer-1"},
                            json={"answer": WORKFLOW_ANSWERS[0]},
                        ),
                    ),
                    timeout=5,
                )
            finally:
                db.transaction = original_transaction

        assert [response.status_code for response in responses] == [200, 200]
        assert sorted(response.json()["idempotent_replay"] for response in responses) == [False, True]
        assert len({response.json()["turn"]["id"] for response in responses}) == 1
        assert await db.fetch_one(
            "SELECT COUNT(*) AS total FROM experience_interview_turns WHERE interview_id = ?",
            (interview["id"],),
        ) == {"total": 1}
        assert await db.fetch_one(
            "SELECT status, current_question_index FROM experience_interviews WHERE id = ?",
            (interview["id"],),
        ) == {"status": "IN_PROGRESS", "current_question_index": 1}
        assert await db.fetch_one(
            "SELECT COUNT(*) AS total FROM audit_logs WHERE action = 'EXPERIENCE_INTERVIEW_ANSWERED' AND resource_id = ?",
            (interview["id"],),
        ) == {"total": 1}
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_concurrent_interview_completion_creates_one_card_and_replays_the_other_request(tmp_path):
    app, db = await _build_app(tmp_path)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            _, interview = await _create_authorized_expert_and_interview(client)
            _set_principal(app, user_id="expert-yueshan")
            interview_url = f"/api/v1/assistant/experience/interviews/{interview['id']}"
            assert (await client.post(f"{interview_url}/accept")).status_code == 200
            await _answer_all_questions(client, interview["id"], "concurrent-complete-answer")

            original_transaction = _synchronize_next_transactions(db)
            try:
                responses = await asyncio.wait_for(
                    asyncio.gather(
                        client.post(f"{interview_url}/complete", headers={"X-Trace-ID": "concurrent-complete-1"}),
                        client.post(f"{interview_url}/complete", headers={"X-Trace-ID": "concurrent-complete-2"}),
                    ),
                    timeout=5,
                )
            finally:
                db.transaction = original_transaction

        assert [response.status_code for response in responses] == [201, 201]
        assert sorted(response.json()["idempotent_replay"] for response in responses) == [False, True]
        assert len({response.json()["card"]["id"] for response in responses}) == 1
        assert await db.fetch_one(
            "SELECT COUNT(*) AS total FROM experience_cards WHERE source_interview_id = ?",
            (interview["id"],),
        ) == {"total": 1}
        assert await db.fetch_one(
            "SELECT COUNT(*) AS total FROM audit_logs WHERE action = 'EXPERIENCE_DRAFT_CREATED'",
        ) == {"total": 1}
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_concurrent_card_confirmation_has_one_winner_and_one_success_audit(tmp_path):
    app, db = await _build_app(tmp_path)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            _, interview = await _create_authorized_expert_and_interview(client)
            _set_principal(app, user_id="expert-yueshan")
            interview_url = f"/api/v1/assistant/experience/interviews/{interview['id']}"
            assert (await client.post(f"{interview_url}/accept")).status_code == 200
            await _answer_all_questions(client, interview["id"], "concurrent-confirm-answer")
            completed = await client.post(f"{interview_url}/complete")
            assert completed.status_code == 201, completed.text
            card_id = completed.json()["card"]["id"]

            original_transaction = _synchronize_next_transactions(db)
            try:
                responses = await asyncio.wait_for(
                    asyncio.gather(
                        client.post(
                            f"/api/v1/assistant/experience/cards/{card_id}/confirm",
                            headers={"X-Trace-ID": "concurrent-confirm-1"},
                        ),
                        client.post(
                            f"/api/v1/assistant/experience/cards/{card_id}/confirm",
                            headers={"X-Trace-ID": "concurrent-confirm-2"},
                        ),
                    ),
                    timeout=5,
                )
            finally:
                db.transaction = original_transaction

        assert sorted(response.status_code for response in responses) == [200, 409]
        assert await db.fetch_one(
            "SELECT status, confirmed_by FROM experience_cards WHERE id = ?",
            (card_id,),
        ) == {"status": "EXPERT_CONFIRMED", "confirmed_by": "expert-yueshan"}
        assert await db.fetch_one(
            "SELECT COUNT(*) AS total FROM experience_reviews WHERE card_id = ? AND action = 'CONFIRM'",
            (card_id,),
        ) == {"total": 1}
        assert await db.fetch_one(
            "SELECT COUNT(*) AS total FROM audit_logs WHERE action = 'EXPERIENCE_CARD_CONFIRMED' AND resource_id = ?",
            (card_id,),
        ) == {"total": 1}
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_expert_cannot_revise_source_excerpts_with_fabricated_text(tmp_path):
    app, db = await _build_app(tmp_path)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            _, interview = await _create_authorized_expert_and_interview(client)
            _set_principal(app, user_id="expert-yueshan")
            interview_url = f"/api/v1/assistant/experience/interviews/{interview['id']}"
            assert (await client.post(f"{interview_url}/accept")).status_code == 200
            answers = (
                "异响随轮速变化，踩刹车时不变大。",
                "先停车断电并检查护板间隙，再决定是否空载试车。",
                "发热、焦味、制动跑偏或轴承松旷时必须停止试车并拖车检修。",
                "适用于悦山景区观光车检修岗位，不适用于载客试车。",
            )
            for index, answer in enumerate(answers, start=1):
                response = await client.post(
                    f"{interview_url}/answers",
                    headers={"Idempotency-Key": f"source-answer-{index}"},
                    json={"answer": answer},
                )
                assert response.status_code == 200, response.text
            completed = await client.post(f"{interview_url}/complete")
            assert completed.status_code == 201, completed.text
            card = completed.json()["card"]

            revised = await client.put(
                f"/api/v1/assistant/experience/cards/{card['id']}",
                json={
                    "source_excerpts": ["伪造原话"],
                    "change_note": "尝试替换来源",
                },
            )

        assert revised.status_code == 422, revised.text
        assert revised.json()["detail"]["code"] == "EXPERIENCE_SOURCE_EXCERPTS_INVALID"
        unchanged = await db.fetch_one(
            "SELECT current_version, source_excerpts_json FROM experience_cards WHERE id = ?",
            (card["id"],),
        )
        assert unchanged["current_version"] == 1
        assert json.loads(unchanged["source_excerpts_json"]) == card["source_excerpts"]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_expert_cannot_confirm_card_with_untraceable_source_excerpts(tmp_path):
    app, db = await _build_app(tmp_path)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            _, interview = await _create_authorized_expert_and_interview(client)
            _set_principal(app, user_id="expert-yueshan")
            interview_url = f"/api/v1/assistant/experience/interviews/{interview['id']}"
            assert (await client.post(f"{interview_url}/accept")).status_code == 200
            answers = (
                "异响随轮速变化，踩刹车时不变大。",
                "先停车断电并检查护板间隙，再决定是否空载试车。",
                "发热、焦味、制动跑偏或轴承松旷时必须停止试车并拖车检修。",
                "适用于悦山景区观光车检修岗位，不适用于载客试车。",
            )
            for index, answer in enumerate(answers, start=1):
                response = await client.post(
                    f"{interview_url}/answers",
                    headers={"Idempotency-Key": f"confirm-source-answer-{index}"},
                    json={"answer": answer},
                )
                assert response.status_code == 200, response.text
            completed = await client.post(f"{interview_url}/complete")
            assert completed.status_code == 201, completed.text
            card = completed.json()["card"]

            await db.execute(
                "UPDATE experience_cards SET source_excerpts_json = ? WHERE id = ?",
                (json.dumps(["伪造原话"], ensure_ascii=False), card["id"]),
            )
            confirmed = await client.post(
                f"/api/v1/assistant/experience/cards/{card['id']}/confirm"
            )

        assert confirmed.status_code == 422, confirmed.text
        assert confirmed.json()["detail"]["code"] == "EXPERIENCE_SOURCE_EXCERPTS_INVALID"
        unchanged = await db.fetch_one(
            "SELECT status, confirmed_by, confirmed_at FROM experience_cards WHERE id = ?",
            (card["id"],),
        )
        assert unchanged == {"status": "DRAFT", "confirmed_by": None, "confirmed_at": None}
        assert await db.fetch_one(
            "SELECT id FROM experience_reviews WHERE card_id = ? AND action = 'CONFIRM'",
            (card["id"],),
        ) is None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_manager_can_complete_employee_experience_workflow_as_bound_expert(
    tmp_path,
):
    app, db = await _build_app(tmp_path)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    acting_params = {"acting_user_id": "expert-yueshan"}
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            _, interview = await _create_authorized_expert_and_interview(client)
            interview_url = f"/api/v1/assistant/experience/interviews/{interview['id']}"

            accepted = await client.post(f"{interview_url}/accept", params=acting_params)
            detail = await client.get(interview_url, params=acting_params)
            assert accepted.status_code == 200, accepted.text
            assert detail.status_code == 200, detail.text

            first_answer = await client.post(
                f"{interview_url}/answers",
                params=acting_params,
                headers={"Idempotency-Key": "acting-answer-1"},
                json={"answer": "声音随轮速变化，踩刹车时不变大。"},
            )
            paused = await client.post(f"{interview_url}/pause", params=acting_params)
            resumed = await client.post(f"{interview_url}/resume", params=acting_params)
            assert first_answer.status_code == 200, first_answer.text
            assert paused.status_code == 200, paused.text
            assert resumed.status_code == 200, resumed.text

            for index, answer in enumerate(
                (
                    "先停车断电检查护板间隙，确认安全后才能空载低速试车。",
                    "发热、焦味、制动跑偏或轴承松旷时必须停止试车并拖车检修。",
                    "适用于悦山景区观光车检修岗位，不适用于载客试车。",
                ),
                start=2,
            ):
                answered = await client.post(
                    f"{interview_url}/answers",
                    params=acting_params,
                    headers={"Idempotency-Key": f"acting-answer-{index}"},
                    json={"answer": answer},
                )
                assert answered.status_code == 200, answered.text

            app.state.experience_draft_extractor = FailingExperienceExtractor()
            failed_extraction = await client.post(
                f"{interview_url}/complete",
                params=acting_params,
                headers={"X-Trace-ID": "acting-extraction-failed-001"},
            )
            assert failed_extraction.status_code == 503, failed_extraction.text
            assert failed_extraction.json()["detail"]["code"] == "EXPERIENCE_EXTRACTION_FAILED"

            app.state.experience_draft_extractor = RecordingExperienceExtractor()
            completed = await client.post(
                f"{interview_url}/complete",
                params=acting_params,
                headers={"X-Trace-ID": "acting-complete-001"},
            )
            assert completed.status_code == 201, completed.text
            card = completed.json()["card"]

            revised = await client.put(
                f"/api/v1/assistant/experience/cards/{card['id']}",
                params=acting_params,
                json={
                    "decision_rule": "先隔离车辆，再检查护板间隙和轮端温度。",
                    "change_note": "代理专家补充检查顺序",
                },
            )
            confirmed = await client.post(
                f"/api/v1/assistant/experience/cards/{card['id']}/confirm",
                params=acting_params,
            )
            assert revised.status_code == 200, revised.text
            assert confirmed.status_code == 200, confirmed.text

            submitted = await client.post(
                f"/api/v1/admin/experience-cards/{card['id']}/submit"
            )
            published = await client.post(
                f"/api/v1/admin/experience-cards/{card['id']}/publish",
                json={"comment": "代理访谈结果已由经理核验。"},
            )
            assert submitted.status_code == 200, submitted.text
            assert published.status_code == 200, published.text

            searched = await client.post(
                "/api/v1/assistant/experience/search",
                params=acting_params,
                json={"query": "雨后轮端异响", "session_id": "acting-session"},
            )
            feedback = await client.post(
                f"/api/v1/assistant/experience/cards/{card['id']}/feedback",
                params=acting_params,
                json={
                    "feedback": "HELPFUL",
                    "session_id": "acting-session",
                    "note": "代理演示确认可用。",
                },
            )
            assert searched.status_code == 200, searched.text
            assert [item["id"] for item in searched.json()["experiences"]] == [card["id"]]
            assert feedback.status_code == 200, feedback.text

        card_row = await db.fetch_one(
            """
            SELECT created_by, updated_by, confirmed_by
            FROM experience_cards WHERE id = ?
            """,
            (card["id"],),
        )
        assert card_row == {
            "created_by": "expert-yueshan",
            "updated_by": "manager-yueshan",
            "confirmed_by": "expert-yueshan",
        }
        reviews = await db.fetch_all(
            """
            SELECT action, actor_id FROM experience_reviews
            WHERE card_id = ? AND action IN ('REVISE', 'CONFIRM')
            ORDER BY created_at
            """,
            (card["id"],),
        )
        assert reviews == [
            {"action": "REVISE", "actor_id": "expert-yueshan"},
            {"action": "CONFIRM", "actor_id": "expert-yueshan"},
        ]
        versions = await db.fetch_all(
            """
            SELECT version_number, created_by FROM experience_card_versions
            WHERE card_id = ? ORDER BY version_number
            """,
            (card["id"],),
        )
        assert versions == [
            {"version_number": 1, "created_by": "expert-yueshan"},
            {"version_number": 2, "created_by": "expert-yueshan"},
        ]
        authorization = await db.fetch_one(
            """
            SELECT created_by FROM experience_authorizations
            WHERE card_id = ?
            """,
            (card["id"],),
        )
        assert authorization["created_by"] == "expert-yueshan"
        usage = await db.fetch_all(
            """
            SELECT usage_type, user_id FROM experience_usage_logs
            WHERE card_id = ? ORDER BY created_at
            """,
            (card["id"],),
        )
        assert usage == [
            {"usage_type": "RETRIEVED", "user_id": "expert-yueshan"},
            {"usage_type": "HELPFUL", "user_id": "expert-yueshan"},
        ]
        draft_audit = await db.fetch_one(
            """
            SELECT user_id, metadata_json FROM audit_logs
            WHERE action = 'EXPERIENCE_DRAFT_CREATED' AND trace_id = ?
            """,
            ("acting-complete-001",),
        )
        assert draft_audit["user_id"] == "manager-yueshan"
        assert json.loads(draft_audit["metadata_json"])["acting_user_id"] == "expert-yueshan"
        failed_audit = await db.fetch_one(
            """
            SELECT user_id, metadata_json FROM audit_logs
            WHERE action = 'EXPERIENCE_EXTRACTION_FAILED' AND trace_id = ?
            """,
            ("acting-extraction-failed-001",),
        )
        assert failed_audit["user_id"] == "manager-yueshan"
        failed_metadata = json.loads(failed_audit["metadata_json"])
        assert failed_metadata["acting_user_id"] == "expert-yueshan"
        assert failed_metadata["actor_user_id"] == "manager-yueshan"
        action_audits = await db.fetch_all(
            """
            SELECT action, user_id, metadata_json FROM audit_logs
            WHERE action IN (
                'EXPERIENCE_INTERVIEW_ACCEPTED',
                'EXPERIENCE_INTERVIEW_ANSWERED',
                'EXPERIENCE_INTERVIEW_PAUSED',
                'EXPERIENCE_INTERVIEW_RESUMED',
                'EXPERIENCE_CARD_REVISED',
                'EXPERIENCE_CARD_CONFIRMED'
            )
            ORDER BY created_at
            """
        )
        action_counts = {
            action: sum(1 for audit in action_audits if audit["action"] == action)
            for action in {
                "EXPERIENCE_INTERVIEW_ACCEPTED",
                "EXPERIENCE_INTERVIEW_ANSWERED",
                "EXPERIENCE_INTERVIEW_PAUSED",
                "EXPERIENCE_INTERVIEW_RESUMED",
                "EXPERIENCE_CARD_REVISED",
                "EXPERIENCE_CARD_CONFIRMED",
            }
        }
        assert action_counts == {
            "EXPERIENCE_INTERVIEW_ACCEPTED": 1,
            "EXPERIENCE_INTERVIEW_ANSWERED": 4,
            "EXPERIENCE_INTERVIEW_PAUSED": 1,
            "EXPERIENCE_INTERVIEW_RESUMED": 1,
            "EXPERIENCE_CARD_REVISED": 1,
            "EXPERIENCE_CARD_CONFIRMED": 1,
        }
        for audit in action_audits:
            assert audit["user_id"] == "manager-yueshan"
            metadata = json.loads(audit["metadata_json"])
            assert metadata["acting_user_id"] == "expert-yueshan"
            assert metadata["actor_user_id"] == "manager-yueshan"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_completed_interview_is_extracted_server_side_from_persisted_answers(tmp_path):
    app, db = await _build_app(tmp_path)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            expert_response = await client.post(
                "/api/v1/admin/experts",
                json={
                    "user_id": "expert-yueshan",
                    "display_name": "张建国",
                    "job_title": "资深设备主管",
                    "department": "设备运营部",
                    "years_experience": 18,
                    "expertise": ["观光车", "雨后复运"],
                    "authorization_status": "SIGNED",
                    "authorization_statement": "本人同意将确认后的经验用于悦山景区组织知识服务。",
                },
            )
            expert = expert_response.json()["expert"]
            interview_response = await client.post(
                "/api/v1/admin/experience-interviews",
                json={
                    "expert_id": expert["id"],
                    "title": "雨后观光车轮端异响判断",
                    "source_event_id": "SJ-20260808-001",
                    "authorization_scopes": [
                        {"scope_type": "VENUE", "scope_value": "venue-yueshan"}
                    ],
                },
            )
            interview = interview_response.json()["interview"]

            _set_principal(app, user_id="expert-yueshan")
            assert (
                await client.post(
                    f"/api/v1/assistant/experience/interviews/{interview['id']}/accept"
                )
            ).status_code == 200
            answers = (
                "声音随轮速变化，踩刹车时不变大；发热和焦味更像制动问题。",
                "先停车断电并检查护板间隙，确认安全后才能空载低速试车。",
                "发热、焦味、制动跑偏或轴承松旷时必须停止试车并拖车检修。",
                "适用于悦山景区观光车和设备检修岗位，不适用于载客试车。",
            )
            for index, answer in enumerate(answers, start=1):
                response = await client.post(
                    f"/api/v1/assistant/experience/interviews/{interview['id']}/answers",
                    headers={"Idempotency-Key": f"answer-{index}"},
                    json={"answer": answer},
                )
                assert response.status_code == 200, response.text

            completed = await client.post(
                f"/api/v1/assistant/experience/interviews/{interview['id']}/complete"
            )
            replayed = await client.post(
                f"/api/v1/assistant/experience/interviews/{interview['id']}/complete"
            )

        assert completed.status_code == 201, completed.text
        body = completed.json()
        assert body["card"]["status"] == "DRAFT"
        assert body["card"]["title"] == "雨后观光车轮端间歇性金属异响判断"
        assert body["card"]["extraction_trace_id"] == body["trace_id"]
        assert body["extraction"]["agent"] == "PersonaExtract"
        assert body["extraction"]["model"] == "deepseek-flash"

        extractor = app.state.experience_draft_extractor
        assert len(extractor.calls) == 1
        call = extractor.calls[0]
        assert call["venue_id"] == "venue-yueshan"
        assert call["evidence"]["expert_name"] == "张建国"
        assert [turn["answer_text"] for turn in call["evidence"]["turns"]] == list(answers)
        assert replayed.status_code == 201, replayed.text
        assert replayed.json()["idempotent_replay"] is True
        assert replayed.json()["card"]["id"] == body["card"]["id"]
        assert len(extractor.calls) == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_interview_cannot_complete_until_all_answers_are_persisted(tmp_path):
    app, db = await _build_app(tmp_path)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            expert_response = await client.post(
                "/api/v1/admin/experts",
                json={
                    "user_id": "expert-yueshan",
                    "display_name": "张建国",
                    "job_title": "资深设备主管",
                    "department": "设备运营部",
                    "years_experience": 18,
                    "expertise": ["观光车", "雨后复运"],
                    "authorization_status": "SIGNED",
                    "authorization_statement": "本人同意将确认后的经验用于悦山景区组织知识服务。",
                },
            )
            expert = expert_response.json()["expert"]
            interview_response = await client.post(
                "/api/v1/admin/experience-interviews",
                json={
                    "expert_id": expert["id"],
                    "title": "雨后观光车轮端异响判断",
                    "authorization_scopes": [
                        {"scope_type": "VENUE", "scope_value": "venue-yueshan"}
                    ],
                },
            )
            interview = interview_response.json()["interview"]

            _set_principal(app, user_id="expert-yueshan")
            accepted = await client.post(
                f"/api/v1/assistant/experience/interviews/{interview['id']}/accept"
            )
            assert accepted.status_code == 200, accepted.text
            answered = await client.post(
                f"/api/v1/assistant/experience/interviews/{interview['id']}/answers",
                headers={"Idempotency-Key": "incomplete-answer-1"},
                json={"answer": "先确认异响是否随轮速变化，再检查制动盘和防尘护板。"},
            )
            assert answered.status_code == 200, answered.text

            completed = await client.post(
                f"/api/v1/assistant/experience/interviews/{interview['id']}/complete"
            )
            detail = await client.get(
                f"/api/v1/assistant/experience/interviews/{interview['id']}"
            )

        assert completed.status_code == 409, completed.text
        assert completed.json()["detail"]["code"] == "INTERVIEW_ANSWERS_INCOMPLETE"
        assert app.state.experience_draft_extractor.calls == []
        assert detail.status_code == 200, detail.text
        assert detail.json()["interview"]["status"] == "IN_PROGRESS"
        assert detail.json()["interview"]["progress"]["answered"] == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_expert_must_sign_experience_authorization_before_interview(tmp_path):
    app, db = await _build_app(tmp_path)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            expert_response = await client.post(
                "/api/v1/admin/experts",
                json={
                    "user_id": "expert-yueshan",
                    "display_name": "张建国",
                    "job_title": "资深设备主管",
                    "department": "设备运营部",
                    "years_experience": 18,
                    "expertise": ["观光车", "雨后复运"],
                },
            )
            assert expert_response.status_code == 201, expert_response.text
            expert = expert_response.json()["expert"]
            assert expert["authorization_status"] == "PENDING"
            assert expert["authorization_signed_at"] is None

            blocked = await client.post(
                "/api/v1/admin/experience-interviews",
                json={
                    "expert_id": expert["id"],
                    "title": "雨后观光车轮端异响判断",
                    "authorization_scopes": [
                        {"scope_type": "VENUE", "scope_value": "venue-yueshan"}
                    ],
                },
            )
            assert blocked.status_code == 409, blocked.text
            assert blocked.json()["detail"]["code"] == "EXPERT_AUTHORIZATION_REQUIRED"

            signed = await client.patch(
                f"/api/v1/admin/experts/{expert['id']}",
                json={
                    "authorization_status": "SIGNED",
                    "authorization_statement": "本人同意将访谈中确认的经验按所选范围用于组织知识服务。",
                },
            )
            invited = await client.post(
                "/api/v1/admin/experience-interviews",
                json={
                    "expert_id": expert["id"],
                    "title": "雨后观光车轮端异响判断",
                    "authorization_scopes": [
                        {"scope_type": "VENUE", "scope_value": "venue-yueshan"}
                    ],
                },
            )

        assert signed.status_code == 200, signed.text
        assert signed.json()["expert"]["authorization_status"] == "SIGNED"
        assert signed.json()["expert"]["authorization_signed_at"] is not None
        assert invited.status_code == 201, invited.text
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_failed_extraction_preserves_answers_is_audited_and_can_be_retried(tmp_path):
    app, db = await _build_app(tmp_path)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            expert_response = await client.post(
                "/api/v1/admin/experts",
                json={
                    "user_id": "expert-yueshan",
                    "display_name": "张建国",
                    "job_title": "资深设备主管",
                    "department": "设备运营部",
                    "years_experience": 18,
                    "expertise": ["观光车", "雨后复运"],
                    "authorization_status": "SIGNED",
                    "authorization_statement": "本人同意将确认后的经验用于悦山景区组织知识服务。",
                },
            )
            expert = expert_response.json()["expert"]
            interview_response = await client.post(
                "/api/v1/admin/experience-interviews",
                json={
                    "expert_id": expert["id"],
                    "title": "雨后观光车轮端异响判断",
                    "authorization_scopes": [
                        {"scope_type": "VENUE", "scope_value": "venue-yueshan"}
                    ],
                },
            )
            interview = interview_response.json()["interview"]

            _set_principal(app, user_id="expert-yueshan")
            accepted = await client.post(
                f"/api/v1/assistant/experience/interviews/{interview['id']}/accept"
            )
            assert accepted.status_code == 200, accepted.text
            answers = (
                "异响随轮速变化，踩刹车时不变大，应先区分护板与制动问题。",
                "先停车断电并检查护板间隙，确认安全后才能空载低速试车。",
                "发热、焦味、制动跑偏或轴承松旷时必须停止试车并拖车检修。",
                "适用于悦山景区观光车检修岗位，不适用于载客试车。",
            )
            for index, answer in enumerate(answers, start=1):
                answered = await client.post(
                    f"/api/v1/assistant/experience/interviews/{interview['id']}/answers",
                    headers={"Idempotency-Key": f"failure-answer-{index}"},
                    json={"answer": answer},
                )
                assert answered.status_code == 200, answered.text

            app.state.experience_draft_extractor = FailingExperienceExtractor()
            failed = await client.post(
                f"/api/v1/assistant/experience/interviews/{interview['id']}/complete",
                headers={"X-Trace-ID": "experience-failure-001"},
            )
            preserved = await client.get(
                f"/api/v1/assistant/experience/interviews/{interview['id']}"
            )

            assert failed.status_code == 503, failed.text
            failure_detail = failed.json()["detail"]
            assert failure_detail["code"] == "EXPERIENCE_EXTRACTION_FAILED"
            assert failure_detail["retryable"] is True
            assert failure_detail["trace_id"] == "experience-failure-001"
            assert preserved.status_code == 200, preserved.text
            assert preserved.json()["interview"]["status"] == "IN_PROGRESS"
            assert preserved.json()["interview"]["progress"]["answered"] == 4
            assert [
                turn["answer_text"] for turn in preserved.json()["interview"]["turns"]
            ] == list(answers)

            app.state.experience_draft_extractor = RecordingExperienceExtractor()
            retried = await client.post(
                f"/api/v1/assistant/experience/interviews/{interview['id']}/complete",
                headers={"X-Trace-ID": "experience-retry-001"},
            )
            assert retried.status_code == 201, retried.text

            _set_principal(app, user_id="manager-yueshan", role="manager")
            audit_response = await client.get(
                "/api/v1/admin/audit-logs",
                params={
                    "trace_id": "experience-failure-001",
                    "action": "EXPERIENCE_EXTRACTION_FAILED",
                },
            )

        assert audit_response.status_code == 200, audit_response.text
        audit_logs = audit_response.json()["audit_logs"]
        assert len(audit_logs) == 1
        assert audit_logs[0]["outcome"] == "FAILED"
        assert audit_logs[0]["metadata"]["agent"] == "PersonaExtract"
        assert audit_logs[0]["metadata"]["model"] == "deepseek-flash"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_experience_card_is_unsearchable_until_expert_confirmation_and_governed_publish(tmp_path):
    app, db = await _build_app(tmp_path)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            expert_response = await client.post(
                "/api/v1/admin/experts",
                json={
                    "user_id": "expert-yueshan",
                    "display_name": "张建国",
                    "job_title": "资深设备主管",
                    "department": "设备运营部",
                    "years_experience": 18,
                    "expertise": ["观光车", "雨后复运"],
                    "authorization_status": "SIGNED",
                    "authorization_statement": "本人同意将确认后的经验用于悦山景区组织知识服务。",
                },
            )
            assert expert_response.status_code == 201, expert_response.text
            expert = expert_response.json()["expert"]
            assert expert["business_id"].startswith("ZJ-")

            interview_response = await client.post(
                "/api/v1/admin/experience-interviews",
                json={
                    "expert_id": expert["id"],
                    "title": "雨后观光车轮端异响判断",
                    "source_event_id": "SJ-20260808-001",
                    "authorization_scopes": [
                        {"scope_type": "VENUE", "scope_value": "venue-yueshan"},
                        {"scope_type": "JOB_TITLE", "scope_value": "设备检修员"},
                    ],
                },
            )
            assert interview_response.status_code == 201, interview_response.text
            interview = interview_response.json()["interview"]
            assert interview["status"] == "INVITED"
            assert interview["business_id"].startswith("FT-")

            _set_principal(app, user_id="expert-yueshan")
            accepted = await client.post(
                f"/api/v1/assistant/experience/interviews/{interview['id']}/accept"
            )
            assert accepted.status_code == 200, accepted.text

            answers = (
                "声音随轮速变化，踩刹车时不变大；发热和焦味更像制动问题。",
                "先停车断电并检查护板间隙，确认安全后才能空载低速试车。",
                "发热、焦味、制动跑偏或轴承松旷时必须停止试车并拖车检修。",
                "适用于悦山景区观光车和设备检修岗位，不适用于载客试车。",
            )
            for index, answer in enumerate(answers, start=1):
                response = await client.post(
                    f"/api/v1/assistant/experience/interviews/{interview['id']}/answers",
                    headers={"Idempotency-Key": f"lifecycle-answer-{index}"},
                    json={"answer": answer},
                )
                assert response.status_code == 200, response.text

            completed = await client.post(
                f"/api/v1/assistant/experience/interviews/{interview['id']}/complete"
            )
            assert completed.status_code == 201, completed.text
            card = completed.json()["card"]
            assert card["status"] == "DRAFT"
            assert card["business_id"].startswith("JY-")
            assert app.state.vector_store.documents == {}

            hidden_search = await client.post(
                "/api/v1/assistant/experience/search",
                json={"query": "雨后轮端异响怎么办"},
            )
            assert hidden_search.status_code == 200
            assert hidden_search.json()["experiences"] == []

            confirmed = await client.post(
                f"/api/v1/assistant/experience/cards/{card['id']}/confirm"
            )
            assert confirmed.status_code == 200, confirmed.text
            assert confirmed.json()["card"]["status"] == "EXPERT_CONFIRMED"

            _set_principal(app, user_id="manager-yueshan", role="manager")
            submitted = await client.post(
                f"/api/v1/admin/experience-cards/{card['id']}/submit"
            )
            assert submitted.status_code == 200, submitted.text
            assert submitted.json()["card"]["status"] == "IN_REVIEW"

            rejected = await client.post(
                f"/api/v1/admin/experience-cards/{card['id']}/reject",
                json={"comment": "请明确禁止试车条件和适用车型。"},
            )
            assert rejected.status_code == 200, rejected.text
            assert rejected.json()["card"]["status"] == "DRAFT"

            _set_principal(app, user_id="expert-yueshan")
            revised = await client.put(
                f"/api/v1/assistant/experience/cards/{card['id']}",
                json={
                    "prohibitions": ["发热、焦味、制动跑偏或轴承松旷时禁止继续试车"],
                    "change_note": "补充禁止试车条件",
                },
            )
            assert revised.status_code == 200, revised.text
            assert revised.json()["card"]["current_version"] == 2
            reconfirmed = await client.post(
                f"/api/v1/assistant/experience/cards/{card['id']}/confirm"
            )
            assert reconfirmed.status_code == 200

            _set_principal(app, user_id="manager-yueshan", role="manager")
            assert (
                await client.post(f"/api/v1/admin/experience-cards/{card['id']}/submit")
            ).status_code == 200
            published = await client.post(
                f"/api/v1/admin/experience-cards/{card['id']}/publish",
                json={"comment": "来源、边界和授权均已核验。"},
            )
            assert published.status_code == 200, published.text
            published_card = published.json()["card"]
            assert published_card["status"] == "PUBLISHED"
            assert published_card["published_version"] == 2
            assert published_card["vector_doc_id"] in app.state.vector_store.documents

            _set_principal(app, user_id="operator-yueshan")
            found = await client.post(
                "/api/v1/assistant/experience/search",
                json={"query": "雨后轮端异响怎么办"},
            )
            assert found.status_code == 200, found.text
            experiences = found.json()["experiences"]
            assert len(experiences) == 1
            assert experiences[0]["business_id"] == card["business_id"]
            assert experiences[0]["source"]["expert_name"] == "张建国"
            assert experiences[0]["source"]["event_id"] == "SJ-20260808-001"
            assert experiences[0]["version"] == 2
            assert experiences[0]["score"] == 0.91
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_vector_failure_keeps_card_out_of_published_and_search_results(tmp_path):
    app, db = await _build_app(tmp_path)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        now = time.time()
        await db.execute(
            """
            INSERT INTO expert_profiles (
                id, business_id, venue_id, user_id, display_name, job_title,
                department, years_experience, expertise_json, status,
                created_by, created_at, updated_at
            ) VALUES ('expert-record', 'ZJ-TEST-001', 'venue-yueshan', 'expert-yueshan',
                '张建国', '资深设备主管', '设备运营部', 18, '[]', 'ACTIVE',
                'manager-yueshan', ?, ?)
            """,
            (now, now),
        )
        await db.execute(
            """
            INSERT INTO experience_cards (
                id, business_id, venue_id, expert_id, source_event_id, title, applicable_context,
                signals_json, decision_rule, recommended_actions_json, rationale,
                prohibitions_json, exceptions_json, source_excerpts_json, status, current_version,
                created_by, created_at, updated_at
            ) VALUES ('card-review', 'JY-TEST-001', 'venue-yueshan', 'expert-record',
                'SJ-TEST-001', '雨后异响判断', '雨后观光车异响', '["异响随轮速变化"]',
                '停车检查', '["检查护板间隙"]', '避免风险',
                '["发热时禁止试车"]', '["轴承松旷时升级检修"]',
                '["发热或焦味时不能继续试车"]', 'IN_REVIEW', 1, 'expert-yueshan', ?, ?)
            """,
            (now, now),
        )
        await db.execute(
            """
            INSERT INTO experience_authorizations (
                id, venue_id, card_id, scope_type, scope_value, created_by, created_at
            ) VALUES ('auth-review', 'venue-yueshan', 'card-review', 'VENUE',
                'venue-yueshan', 'manager-yueshan', ?)
            """,
            (now,),
        )
        app.state.vector_store.fail_next_upsert = True
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/admin/experience-cards/card-review/publish",
                json={"comment": "同意发布"},
            )
            assert response.status_code == 503
            card = await db.fetch_one("SELECT status, published_version FROM experience_cards WHERE id = ?", ("card-review",))
            assert card == {"status": "IN_REVIEW", "published_version": None}
            assert app.state.vector_store.documents == {}
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_search_result_is_not_logged_as_referenced_until_answer_uses_it(tmp_path):
    app, db = await _build_app(tmp_path)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        now = time.time()
        await db.execute(
            """
            INSERT INTO expert_profiles (
                id, business_id, venue_id, user_id, display_name, job_title,
                department, years_experience, expertise_json,
                authorization_status, authorization_statement,
                authorization_signed_at, status, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '[]', 'SIGNED', ?, ?, 'ACTIVE', ?, ?, ?)
            """,
            (
                "expert-search",
                "ZJ-SEARCH-001",
                "venue-yueshan",
                "expert-yueshan",
                "张建国",
                "资深设备主管",
                "设备运营部",
                18,
                "本人同意将确认后的经验用于悦山景区组织知识服务。",
                now,
                "manager-yueshan",
                now,
                now,
            ),
        )
        await db.execute(
            """
            INSERT INTO experience_cards (
                id, business_id, venue_id, expert_id, source_event_id,
                title, applicable_context, signals_json, decision_rule,
                recommended_actions_json, rationale, prohibitions_json,
                exceptions_json, source_excerpts_json, status,
                current_version, published_version, vector_doc_id, index_status,
                created_by, updated_by, published_by, published_at,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PUBLISHED',
                1, 1, ?, 'INDEXED', ?, ?, ?, ?, ?, ?)
            """,
            (
                "card-search",
                "JY-SEARCH-001",
                "venue-yueshan",
                "expert-search",
                "SJ-SEARCH-001",
                "雨后观光车轮端异响判断",
                "观光车淋雨后出现随轮速变化的轻微金属擦声",
                '["异响随轮速变化"]',
                "先停车隔离，再检查防尘护板间隙",
                '["停车断电", "检查护板间隙"]',
                "避免将护板摩擦误判为制动故障",
                '["发热或焦味时禁止继续试车"]',
                '["轴承松旷时升级拖车检修"]',
                '["发热、焦味或制动跑偏时必须停止试车。"]',
                "experience:card-search:v1",
                "expert-yueshan",
                "manager-yueshan",
                "manager-yueshan",
                now,
                now,
                now,
            ),
        )
        await db.execute(
            """
            INSERT INTO experience_authorizations (
                id, venue_id, card_id, scope_type, scope_value, created_by, created_at
            ) VALUES (?, ?, ?, 'VENUE', ?, ?, ?)
            """,
            (
                "auth-search",
                "venue-yueshan",
                "card-search",
                "venue-yueshan",
                "manager-yueshan",
                now,
            ),
        )
        app.state.vector_store.upsert_experience(
            "雨后观光车轮端异响判断",
            {"card_id": "card-search", "venue_id": "venue-yueshan"},
            "experience:card-search:v1",
            strict=True,
        )
        _set_principal(app, user_id="operator-yueshan")

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/assistant/experience/search",
                json={"query": "雨后轮端异响怎么办", "session_id": "session-search"},
            )

        assert response.status_code == 200, response.text
        assert [item["id"] for item in response.json()["experiences"]] == ["card-search"]
        usage_rows = await db.fetch_all(
            """
            SELECT usage_type, card_id, user_id, session_id, query_text,
                   experience_version
            FROM experience_usage_logs
            ORDER BY created_at
            """
        )
        assert usage_rows == [
            {
                "usage_type": "RETRIEVED",
                "card_id": "card-search",
                "user_id": "operator-yueshan",
                "session_id": "session-search",
                "query_text": "雨后轮端异响怎么办",
                "experience_version": 1,
            }
        ]

        _set_principal(app, user_id="manager-yueshan", role="manager")
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            detail_response = await client.get(
                "/api/v1/admin/experience-cards/card-search"
            )

        assert detail_response.status_code == 200, detail_response.text
        detail = detail_response.json()["experience_card"]
        assert detail["usage_summary"] == {
            "total": 1,
            "retrieved": 1,
            "viewed": 0,
            "referenced": 0,
            "feedback": 0,
        }
        assert len(detail["usage_records"]) == 1
        usage_record = detail["usage_records"][0]
        assert usage_record == {
            "usage_type": "RETRIEVED",
            "user_display_name": "周琪",
            "query_text": "雨后轮端异响怎么办",
            "score": 0.91,
            "note": None,
            "experience_version": 1,
            "created_at": usage_record["created_at"],
        }
        assert usage_record["created_at"] > 0
        for technical_field in (
            "user_id",
            "message_id",
            "trace_id",
            "retrieval_snapshot_id",
            "agent_id",
            "idempotency_key",
        ):
            assert technical_field not in usage_record

        _set_principal(app, user_id="operator-yueshan")
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            feedback_response = await client.post(
                "/api/v1/assistant/experience/cards/card-search/feedback",
                json={
                    "feedback": "HELPFUL",
                    "session_id": "session-search",
                    "note": "已按建议完成停车隔离和护板检查。",
                },
            )
        assert feedback_response.status_code == 200, feedback_response.text

        _set_principal(app, user_id="manager-yueshan", role="manager")
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            updated_detail_response = await client.get(
                "/api/v1/admin/experience-cards/card-search"
            )
        updated_detail = updated_detail_response.json()["experience_card"]
        assert updated_detail["usage_summary"] == {
            "total": 2,
            "retrieved": 1,
            "viewed": 0,
            "referenced": 0,
            "feedback": 1,
        }
        feedback_record = next(
            record
            for record in updated_detail["usage_records"]
            if record["usage_type"] == "HELPFUL"
        )
        assert feedback_record["user_display_name"] == "周琪"
        assert feedback_record["experience_version"] == 1
        assert feedback_record["note"] == "已按建议完成停车隔离和护板检查。"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_paused_interview_resumes_after_app_restart_without_duplicate_answers(tmp_path):
    app, db = await _build_app(tmp_path)
    database_path = tmp_path / "experience-assets.db"
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            expert_response = await client.post(
                "/api/v1/admin/experts",
                json={
                    "user_id": "expert-yueshan",
                    "display_name": "张建国",
                    "job_title": "车辆检修专家",
                    "department": "设备保障部",
                    "expertise": ["观光车检修"],
                    "authorization_status": "SIGNED",
                    "authorization_statement": "本人同意将确认后的经验用于悦山景区组织知识服务。",
                },
            )
            assert expert_response.status_code == 201, expert_response.text
            interview_response = await client.post(
                "/api/v1/admin/experience-interviews",
                json={
                    "expert_id": expert_response.json()["expert"]["id"],
                    "title": "雨后观光车轮端异响判断",
                    "source_event_id": "event-restart-001",
                    "authorization_scopes": [
                        {"scope_type": "VENUE", "scope_value": "venue-yueshan"}
                    ],
                },
            )
            assert interview_response.status_code == 201, interview_response.text
            interview_id = interview_response.json()["interview"]["id"]

            _set_principal(app, user_id="expert-yueshan")
            accepted = await client.post(
                f"/api/v1/assistant/experience/interviews/{interview_id}/accept"
            )
            answered = await client.post(
                f"/api/v1/assistant/experience/interviews/{interview_id}/answers",
                headers={"Idempotency-Key": "restart-answer-1"},
                json={"answer": "先确认异响是否随轮速变化，再检查制动盘与护板间隙。"},
            )
            paused = await client.post(
                f"/api/v1/assistant/experience/interviews/{interview_id}/pause"
            )
            assert accepted.status_code == 200, accepted.text
            assert answered.status_code == 200, answered.text
            assert paused.status_code == 200, paused.text
            assert paused.json()["interview"]["status"] == "PAUSED"
    finally:
        await db.close()

    restarted_db = AsyncDBClient(database_path)
    await init_database(restarted_db)
    restarted_app = FastAPI()
    restarted_app.state.db_client = restarted_db
    restarted_app.state.vector_store = RecordingVectorStore()
    restarted_app.state.experience_draft_extractor = RecordingExperienceExtractor()
    restarted_app.state.test_principal = {
        "user_id": "expert-yueshan",
        "username": "expert-yueshan",
        "role": "operator",
        "venue_id": "venue-yueshan",
        "auth_type": "test",
    }

    async def restarted_principal():
        return restarted_app.state.test_principal

    restarted_app.dependency_overrides[require_auth] = restarted_principal
    restarted_app.include_router(admin_router, prefix="/api/v1/admin")
    restarted_app.include_router(management_router, prefix="/api/v1/admin")
    restarted_app.include_router(assistant_router, prefix="/api/v1/assistant")
    restarted_transport = httpx.ASGITransport(
        app=restarted_app,
        raise_app_exceptions=False,
    )
    try:
        async with httpx.AsyncClient(
            transport=restarted_transport,
            base_url="http://test",
        ) as client:
            restored = await client.get(
                f"/api/v1/assistant/experience/interviews/{interview_id}"
            )
            resumed = await client.post(
                f"/api/v1/assistant/experience/interviews/{interview_id}/resume"
            )
            replayed = await client.post(
                f"/api/v1/assistant/experience/interviews/{interview_id}/answers",
                headers={"Idempotency-Key": "restart-answer-1"},
                json={"answer": "重复提交不应覆盖已保存答案。"},
            )
            next_answer = await client.post(
                f"/api/v1/assistant/experience/interviews/{interview_id}/answers",
                headers={"Idempotency-Key": "restart-answer-2"},
                json={"answer": "雨后先停车断电检查，确认安全后只能空载低速试车。"},
            )
            refreshed = await client.get(
                f"/api/v1/assistant/experience/interviews/{interview_id}"
            )

        assert restored.status_code == 200, restored.text
        assert restored.json()["interview"]["status"] == "PAUSED"
        assert restored.json()["interview"]["progress"]["answered"] == 1
        assert len(restored.json()["interview"]["turns"]) == 1
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["interview"]["status"] == "IN_PROGRESS"
        assert replayed.status_code == 200, replayed.text
        assert replayed.json()["idempotent_replay"] is True
        assert next_answer.status_code == 200, next_answer.text
        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.json()["interview"]["progress"]["answered"] == 2
        assert len(refreshed.json()["interview"]["turns"]) == 2
        assert refreshed.json()["interview"]["turns"][0]["answer_text"] == (
            "先确认异响是否随轮速变化，再检查制动盘与护板间隙。"
        )
    finally:
        await restarted_db.close()
