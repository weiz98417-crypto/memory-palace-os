import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from src.memory_palace.api.v1.router import router as v1_router
from src.memory_palace.api.v1.endpoints.messages import router
from src.memory_palace.api.auth import require_auth
from src.memory_palace.core.container import AppContainer
from src.memory_palace.core.gateway import router as wechat_router
from src.memory_palace.core.message_runs import MessageRunRepository
from src.memory_palace.core.orchestrator import Orchestrator
from src.memory_palace.core.queue_worker import set_message_queue
from src.memory_palace.core.queue_worker import MessageQueueWorker
from src.memory_palace.knowledge.db_client import AsyncDBClient
from src.memory_palace.knowledge.db_init import init_database
from src.memory_palace.knowledge.evidence_backed_retrieval import (
    EvidenceBackedKnowledgeRetriever,
)
from src.memory_palace.knowledge.experience_schema import init_experience_schema
from src.memory_palace.knowledge.push_logger import record_reply_delivery
from src.memory_palace.tools.llm_wrapper import LLMClient


async def assert_real_wecom_policy_rejection(
    repository,
    db_client,
    *,
    message_id,
    venue_id,
    wechat_client=None,
):
    message_run = await repository.get(message_id)
    delivery = await db_client.fetch_one(
        """
        SELECT * FROM push_logs
        WHERE venue_id = ? AND channel = ? AND idempotency_key = ?
        """,
        (venue_id, "WECOM_REPLY", f"assistant-reply:{message_id}"),
    )
    assert message_run["status"] == "FAILED"
    assert message_run["retryable"] is False
    assert message_run["delivery_status"] == "DISABLED_BY_POLICY"
    assert message_run["delivery_error"]
    assert message_run["delivered_at"] is None
    assert delivery["delivery_status"] == "DISABLED_BY_POLICY"
    assert delivery["delivery_error"] == message_run["delivery_error"]
    assert delivery["adoption_status"] == "not_applicable"
    if wechat_client is not None:
        for method_name in ("send_text", "send_markdown", "send_textcard"):
            method = getattr(wechat_client, method_name, None)
            if method is not None and hasattr(method, "assert_not_awaited"):
                method.assert_not_awaited()


async def build_test_app(tmp_path):
    db_client = AsyncDBClient(tmp_path / "message-runs.db")
    await db_client.execute(
        """
        CREATE TABLE message_runs (
            message_id TEXT PRIMARY KEY,
            trace_id TEXT UNIQUE NOT NULL,
            session_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            venue_id TEXT NOT NULL,
            content TEXT NOT NULL,
            status TEXT NOT NULL,
            target_agent TEXT,
            reply_text TEXT,
            result_json TEXT DEFAULT '{}',
            error TEXT,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 4,
            manual_retry_count INTEGER NOT NULL DEFAULT 0,
            dead_letter_id TEXT,
            delivery_status TEXT NOT NULL DEFAULT 'PENDING',
            delivery_error TEXT,
            delivered_at REAL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            processed_at REAL
        )
        """
    )
    await db_client.execute(
        """
        CREATE TABLE audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            venue_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            action TEXT NOT NULL,
            resource_type TEXT NOT NULL,
            resource_id TEXT,
            outcome TEXT NOT NULL,
            trace_id TEXT NOT NULL,
            metadata_json TEXT DEFAULT '{}',
            created_at REAL NOT NULL
        )
        """
    )
    await db_client.execute(
        """
        CREATE TABLE sessions (
            session_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            venue_id TEXT NOT NULL,
            agent_name TEXT DEFAULT '',
            stage TEXT NOT NULL DEFAULT 'active',
            message_count INTEGER DEFAULT 0,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )

    queue = asyncio.Queue()
    set_message_queue(queue)

    app = FastAPI()
    app.state.db_client = db_client
    app.state.test_principal = {
        "user_id": "operator-test",
        "username": "operator-test",
        "role": "operator",
        "venue_id": "west-lake-park",
        "auth_type": "test",
    }

    async def authenticated_principal():
        return app.state.test_principal

    app.dependency_overrides[require_auth] = authenticated_principal
    app.include_router(router, prefix="/messages")
    return app, queue, db_client


@pytest.mark.asyncio
async def test_message_intake_rejects_foreign_session_before_persistence_or_queue(tmp_path):
    app, queue, db_client = await build_test_app(tmp_path)
    await db_client.execute(
        """
        INSERT INTO sessions (
            session_id, user_id, venue_id, agent_name, stage,
            message_count, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "shared-session",
            "operator-east",
            "east-lake-park",
            "router",
            "active",
            1,
            time.time(),
            time.time(),
        ),
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/messages/",
            json={"content": "尝试复用其他场地会话", "session_id": "shared-session"},
        )

    assert response.status_code == 404
    assert queue.empty()
    assert await db_client.fetch_one(
        "SELECT message_id FROM message_runs WHERE session_id = ?",
        ("shared-session",),
    ) is None
    session = await db_client.fetch_one(
        "SELECT venue_id FROM sessions WHERE session_id = ?",
        ("shared-session",),
    )
    assert session["venue_id"] == "east-lake-park"
    await db_client.close()


@pytest.mark.asyncio
async def test_message_intake_rejects_another_employee_session_in_same_venue(tmp_path):
    app, queue, db_client = await build_test_app(tmp_path)
    now = time.time()
    await db_client.execute(
        """
        INSERT INTO sessions (
            session_id, user_id, venue_id, agent_name, stage,
            message_count, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "same-venue-private-session",
            "operator-other",
            "west-lake-park",
            "router",
            "active",
            1,
            now,
            now,
        ),
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/messages/",
            json={
                "content": "尝试复用同场地其他员工会话",
                "session_id": "same-venue-private-session",
            },
        )

    assert response.status_code == 404
    assert queue.empty()
    assert await db_client.fetch_one(
        "SELECT message_id FROM message_runs WHERE session_id = ?",
        ("same-venue-private-session",),
    ) is None
    await db_client.close()


@pytest.mark.asyncio
async def test_orchestrator_rejects_foreign_session_without_saving_message(tmp_path):
    db_client = AsyncDBClient(tmp_path / "orchestrator-session-boundary.db")
    await init_database(db_client)
    now = time.time()
    await db_client.execute(
        """
        INSERT INTO sessions (
            session_id, user_id, venue_id, agent_name, stage,
            message_count, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "shared-session",
            "operator-east",
            "east-lake-park",
            "router",
            "active",
            1,
            now,
            now,
        ),
    )
    container = AppContainer()
    container.override(db_client=db_client)

    with pytest.raises(ValueError, match="会话不属于当前场地"):
        await Orchestrator(container=container)._save_message(
            {
                "msg_id": "foreign-session-message",
                "session_id": "shared-session",
                "from_user": "operator-west",
                "venue_id": "west-lake-park",
                "msg_type": "text",
                "content": "不得写入其他场地会话",
                "metadata": {"venue_id": "west-lake-park"},
            }
        )

    session = await db_client.fetch_one(
        "SELECT venue_id, message_count FROM sessions WHERE session_id = ?",
        ("shared-session",),
    )
    assert session == {"venue_id": "east-lake-park", "message_count": 1}
    assert await db_client.fetch_one(
        "SELECT message_id FROM messages WHERE message_id = ?",
        ("foreign-session-message",),
    ) is None
    await db_client.close()


class AsyncOnlyQueue:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.messages = []

    async def put(self, message):
        if self.fail:
            raise RuntimeError("simulated queue outage")
        self.messages.append(message)
        return True


async def build_wechat_gateway_app(tmp_path, queue):
    db_client = AsyncDBClient(tmp_path / "wechat-gateway.db")
    await init_database(db_client)
    now = time.time()
    await db_client.execute(
        "INSERT INTO venues (id, name, status, created_at, updated_at) VALUES (?, ?, 'ACTIVE', ?, ?)",
        ("west-lake-park", "西湖景区", now, now),
    )
    await db_client.execute(
        """
        INSERT INTO users (
            id, username, password_hash, display_name, role, venue_id,
            status, created_at, updated_at
        ) VALUES (?, ?, 'test-password', ?, 'operator', ?, 'ACTIVE', ?, ?)
        """,
        (
            "operator-wechat",
            "operator-wechat",
            "企微现场员工",
            "west-lake-park",
            now,
            now,
        ),
    )
    await db_client.execute(
        """
        INSERT INTO channel_identities (
            id, venue_id, channel, external_tenant_id, external_user_id,
            user_id, status, created_at, updated_at
        ) VALUES (?, ?, 'WECOM', ?, ?, ?, 'ACTIVE', ?, ?)
        """,
        (
            "wechat-binding-001",
            "west-lake-park",
            "corp-west",
            "operator-wechat",
            "operator-wechat",
            now,
            now,
        ),
    )
    app = FastAPI()
    app.state.message_queue = queue
    app.state.db_client = db_client
    app.include_router(wechat_router, prefix="/webhook")
    return app, db_client


class DeterministicVectorStore:
    def __init__(self, sop_id=2101):
        self.upserts = []
        self.queries = []
        self.sop_id = sop_id

    def upsert_experience(self, content, metadata, document_id, strict=False):
        self.upserts.append(
            {
                "content": content,
                "metadata": metadata,
                "document_id": document_id,
                "strict": strict,
            }
        )
        return True

    def delete_experience(self, document_id, strict=False):
        self.upserts = [item for item in self.upserts if item["document_id"] != document_id]
        return True

    def health(self):
        return {"status": "healthy"}


    def query_experience(self, text, top_k, threshold, venue_id=None, strict=False):
        self.queries.append(
            {
                "text": text,
                "top_k": top_k,
                "threshold": threshold,
                "venue_id": venue_id,
            }
        )
        return [
            {
                "id": f"sop:{venue_id}:{self.sop_id}",
                "content": "先断电封控，再疏导游客并通知维保人员。",
                "score": 0.93,
                "metadata": {
                    "source_id": str(self.sop_id),
                    "source_type": "SOP",
                    "title": "观光车雨后复运与异常异响处置",
                    "version": "2.1",
                    "status": "PUBLISHED",
                    "published_at": 1785283200.0,
                    "publisher_name": "王敏",
                    "venue_id": venue_id,
                },
            }
        ]


class UnavailableVectorStore(DeterministicVectorStore):
    def query_experience(self, text, top_k, threshold, venue_id=None, strict=False):
        self.queries.append(
            {
                "text": text,
                "top_k": top_k,
                "threshold": threshold,
                "venue_id": venue_id,
            }
        )
        if strict:
            raise RuntimeError("simulated Chroma outage")
        return []


class EmptyVectorStore(DeterministicVectorStore):
    def query_experience(self, text, top_k, threshold, venue_id=None, strict=False):
        self.queries.append(
            {
                "text": text,
                "top_k": top_k,
                "threshold": threshold,
                "venue_id": venue_id,
            }
        )
        return []


class DraftSopVectorStore(DeterministicVectorStore):
    def query_experience(self, text, top_k, threshold, venue_id=None, strict=False):
        documents = super().query_experience(
            text,
            top_k,
            threshold,
            venue_id=venue_id,
            strict=strict,
        )
        documents[0]["metadata"]["status"] = "DRAFT"
        return documents


class SopAndAuthorizedExperienceVectorStore(DeterministicVectorStore):
    def query_experience(self, text, top_k, threshold, venue_id=None, strict=False):
        documents = super().query_experience(
            text,
            top_k,
            threshold,
            venue_id=venue_id,
            strict=strict,
        )
        documents.append(
            {
                "id": "experience:west-lake-park:experience-card-1:v1",
                "content": "雨后异响随轮速变化且不随制动变化时，先检查防尘护板间隙。",
                "score": 0.91,
                "metadata": {
                    "card_id": "experience-card-1",
                    "source_type": "EXPERIENCE_CARD",
                    "title": "雨后观光车轮端间歇性金属异响判断",
                    "version": "1",
                    "status": "PUBLISHED",
                    "published_at": 1785290400.0,
                    "publisher_name": "王敏",
                    "venue_id": venue_id,
                },
            }
        )
        return documents


async def seed_authorized_experience(db_client, *, authorize=True):
    await init_experience_schema(db_client)
    now = 1785290400.0
    await db_client.execute(
        """
        INSERT INTO users (
            id, username, password_hash, display_name, role, venue_id,
            department, job_title, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'operator', ?, ?, ?, 'ACTIVE', ?, ?)
        """,
        (
            "operator-golden-chain",
            "operator-golden-chain",
            "test-only-password-hash",
            "周琪",
            "west-lake-park",
            "运营部",
            "早班运营员",
            now,
            now,
        ),
    )
    await db_client.execute(
        """
        INSERT INTO expert_profiles (
            id, business_id, venue_id, user_id, display_name, job_title,
            department, years_experience, expertise_json, authorization_status,
            authorization_statement, authorization_signed_at, status, created_by,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 12, '[]', 'APPROVED', ?, ?, 'ACTIVE', ?, ?, ?)
        """,
        (
            "expert-1",
            "ZJ-20260808-0001",
            "west-lake-park",
            "expert-user-1",
            "张建国",
            "资深设备主管",
            "设备运营部",
            "同意在悦山景区设备运营岗位范围内使用本人已确认经验",
            now,
            "knowledge-owner",
            now,
            now,
        ),
    )
    await db_client.execute(
        """
        INSERT INTO confirmed_events (
            event_id, business_id, push_id, from_user, raw_text, event_type,
            severity, context_trigger_data, memory_content, vector_doc_id,
            created_at, confirmed_at, venue_id, source_type, status, assigned_to,
            resolution, trace_id, closed_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, '{}', ?, ?, ?, ?, ?, 'LIVE', 'CLOSED', ?, ?, ?, ?, ?)
        """,
        (
            "source-event-1",
            "SJ-20260808-0001",
            "source-message-1",
            "operator-golden-chain",
            "12号观光车雨后出现右后轮间歇性金属摩擦声",
            "设备异响",
            "P1",
            "雨后护板轻微变形并与制动盘间歇摩擦",
            "event:west-lake-park:source-event-1",
            now - 7200,
            now - 7100,
            "west-lake-park",
            "knowledge-owner",
            "更换防松螺栓、校正护板并完成空载三轮试车。",
            "trace-source-event-1",
            now - 3600,
            now - 3600,
        ),
    )
    await db_client.execute(
        """
        INSERT INTO experience_cards (
            id, business_id, venue_id, expert_id, source_event_id, title, applicable_context,
            signals_json, decision_rule, recommended_actions_json, rationale,
            prohibitions_json, exceptions_json, source_excerpts_json, status,
            current_version, published_version, vector_doc_id, index_status,
            created_by, published_by, published_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PUBLISHED', 1, 1, ?, 'INDEXED', ?, ?, ?, ?, ?)
        """,
        (
            "experience-card-1",
            "JY-20260808-0001",
            "west-lake-park",
            "expert-1",
            "source-event-1",
            "雨后观光车轮端间歇性金属异响判断",
            "雨后晨检发现随车速变化、但不随制动变化的轻微金属擦声",
            '["异响随轮速变化", "踩刹车时声音没有明显变大", "无发热和焦味"]',
            "未完成防尘护板间隙检查前不得载客",
            '["保持停运", "隔离车辆", "检查防尘护板间隙"]',
            "雨后护板可能轻微变形并与制动盘间歇摩擦",
            '["不得带客试车"]',
            '["发热、焦味或制动跑偏时立即停止试车并升级处理"]',
            '["昨天淋雨后出现随轮速变化的间歇性擦声"]',
            "experience:west-lake-park:experience-card-1:v1",
            "knowledge-owner",
            "knowledge-owner",
            now,
            now,
            now,
        ),
    )
    if authorize:
        await db_client.execute(
            """
            INSERT INTO experience_authorizations (
                id, venue_id, card_id, scope_type, scope_value, created_by, created_at
            ) VALUES (?, ?, ?, 'VENUE', ?, ?, ?)
            """,
            (
                "authorization-1",
                "west-lake-park",
                "experience-card-1",
                "west-lake-park",
                "knowledge-owner",
                now,
            ),
        )


_USE_LIVE_VECTOR_STORE = object()


async def build_golden_chain_app(
    tmp_path,
    monkeypatch,
    *,
    router_intent="incident_report",
    push_succeeds=False,
    use_real_push_logger=False,
    retrieval_vector_store_factory=_USE_LIVE_VECTOR_STORE,
):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("MOCK_LLM", "true")
    push_writer = None
    if not use_real_push_logger:
        push_writer = AsyncMock(return_value="push-test")
        monkeypatch.setattr("src.memory_palace.knowledge.push_logger.write_push_log", push_writer)
    if push_succeeds:
        monkeypatch.setattr(
            "src.memory_palace.skills.context_trigger.skill.ContextTriggerSkill._trigger_wechat_push",
            AsyncMock(return_value=True),
        )

    db_client = AsyncDBClient(tmp_path / "golden-chain.db")
    await init_database(db_client)
    await db_client.execute(
        """
        INSERT INTO venues (id, name, status, created_at, updated_at)
        VALUES (?, ?, 'ACTIVE', ?, ?)
        """,
        ("west-lake-park", "西湖园区", 1785283200.0, 1785283200.0),
    )
    await db_client.execute(
        """
        INSERT INTO users (
            id, username, password_hash, display_name, role, venue_id,
            status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'manager', ?, 'ACTIVE', ?, ?)
        """,
        (
            "knowledge-owner",
            "knowledge-owner",
            "test-only-password-hash",
            "王敏",
            "west-lake-park",
            1785283200.0,
            1785283200.0,
        ),
    )
    await db_client.execute(
        """
        INSERT INTO sop_documents (
            id, venue_id, category, title, content, priority, version, status,
            created_by, reviewed_by, published_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'PUBLISHED', ?, ?, ?, ?, ?)
        """,
        (
            2101,
            "west-lake-park",
            "设备安全",
            "观光车雨后复运与异常异响处置",
            "保持车辆停运并隔离，保管钥匙，完成轮端检查前禁止载客。",
            1,
            "2.1",
            "knowledge-owner",
            "knowledge-owner",
            1785283200.0,
            1785283200.0,
            1785283200.0,
        ),
    )
    await db_client.execute(
        """
        INSERT INTO knowledge_documents (
            id, venue_id, title, content, category, source_type, source_id,
            version, status, tags_json, vector_doc_id, created_by, updated_by,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'SOP', ?, ?, 'ACTIVE', '[]', ?, ?, ?, ?, ?)
        """,
        (
            "sop-2101",
            "west-lake-park",
            "观光车雨后复运与异常异响处置",
            "保持车辆停运并隔离，保管钥匙，完成轮端检查前禁止载客。",
            "设备安全",
            "2101",
            1,
            "sop:west-lake-park:2101",
            "knowledge-owner",
            "knowledge-owner",
            1785283200.0,
            1785283200.0,
        ),
    )

    llm_client = LLMClient()
    llm_client.set_database(db_client)

    def deterministic_mock_json(prompt_context):
        if "KEYWORD HITS" in prompt_context:
            return json.dumps(
                {
                    "trigger": True,
                    "severity": "P1",
                    "event_type": "设施故障",
                    "confidence": 0.98,
                    "reason": "扶梯停运需要现场应急处置",
                },
                ensure_ascii=False,
            )
        if "required_tools" in prompt_context and "next_step_check" in prompt_context:
            return json.dumps(
                {
                    "reply_text": "已启动扶梯停运现场处置流程",
                    "action_taken": "dispatch_maintenance_team",
                    "required_tools": [],
                    "next_step_check": "确认扶梯断电并完成游客疏导",
                },
                ensure_ascii=False,
            )
        if "处突与记忆专家" in prompt_context:
            return json.dumps(
                {
                    "reply_text": "根据 2026-07-01 的历史记录，先断电封控并疏导游客。",
                    "action_taken": "rag_experience_advice",
                    "structured_data": {
                        "is_hallucination_prevented": False,
                        "reasoning_log": "命中同场地扶梯停运案例",
                    },
                },
                ensure_ascii=False,
            )
        if "AUTHORIZED_EXPERIENCE_SYNTHESIS" in prompt_context:
            return json.dumps(
                {
                    "reply_text": "不能直接载客。请保持停运并检查右后轮防尘护板间隙；如出现发热、焦味或制动跑偏，立即停止试车并升级处理。",
                    "emotion_state": "neutral",
                    "interview_stage": "resolved",
                    "is_completed": True,
                    "used_experience_card_ids": ["experience-card-1"],
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "intent": router_intent,
                "severity": "P1",
                "summary": "东门扶梯停运",
                "is_critical": True,
                "confidence": 0.97,
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(llm_client, "_mock_json", deterministic_mock_json)
    for module_name in (
        "src.memory_palace.skills.context_trigger.skill.llm_client",
        "src.memory_palace.skills.router.skill.llm_client",
        "src.memory_palace.skills.commander.skill.llm_client",
        "src.memory_palace.skills.memory_ops.skill.llm_client",
        "src.memory_palace.skills.persona.skill.llm_client",
    ):
        monkeypatch.setattr(module_name, llm_client)

    vector_store = DeterministicVectorStore()
    retrieval_vector_store = (
        vector_store
        if retrieval_vector_store_factory is _USE_LIVE_VECTOR_STORE
        else retrieval_vector_store_factory()
    )
    container = AppContainer()
    container.override(
        db_client=db_client,
        vector_store=vector_store,
        knowledge_retriever=EvidenceBackedKnowledgeRetriever(
            database=db_client,
            vector_store=retrieval_vector_store,
        ),
        wechat_client=None,
    )
    queue = asyncio.Queue()
    set_message_queue(queue)

    app = FastAPI()
    app.state.db_client = db_client
    app.state.push_writer = push_writer
    app.state.vector_store = vector_store
    app.state.test_principal = {
        "user_id": "operator-golden-chain",
        "username": "operator-golden-chain",
        "role": "operator",
        "venue_id": "west-lake-park",
        "auth_type": "test",
    }

    async def authenticated_principal():
        return app.state.test_principal

    app.dependency_overrides[require_auth] = authenticated_principal
    app.include_router(v1_router)
    worker = MessageQueueWorker(
        queue=queue,
        concurrency=1,
        orchestrator=Orchestrator(container=container),
        container=container,
    )
    return app, db_client, vector_store, worker


@pytest.mark.asyncio
async def test_formal_message_intake_runs_incident_agent_chain_and_keeps_event_open(
    tmp_path,
    monkeypatch,
):
    app, db_client, vector_store, worker = await build_golden_chain_app(tmp_path, monkeypatch)
    worker_task = asyncio.create_task(worker.start())
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            accepted_response = await client.post(
                "/api/v1/messages/",
                json={
                    "content": "东门扶梯突然停运，现场有游客滞留",
                    "session_id": "session-golden-chain",
                },
            )
            assert accepted_response.status_code == 202
            accepted = accepted_response.json()

            message_status = None
            for _ in range(100):
                status_response = await client.get(f"/api/v1/messages/{accepted['message_id']}")
                assert status_response.status_code == 200
                message_status = status_response.json()
                if message_status["status"] in {"COMPLETED", "FAILED"}:
                    break
                await asyncio.sleep(0.01)

            assert message_status["status"] == "COMPLETED"
            assert message_status["trace_id"] == accepted["trace_id"]
            assert message_status["session_id"] == accepted["session_id"]
            assert "target_agent" not in message_status
            assert "result" not in message_status
            internal_run = await MessageRunRepository(db_client).get(accepted["message_id"])
            assert internal_run["target_agent"] == "commander"
            internal_result = internal_run["result"]
            agent_trace = internal_result["agent_trace"]
            assert [step["agent_id"] for step in agent_trace] == [
                "ContextTrigger",
                "Router",
                "MemoryOps",
                "Commander",
            ]
            assert all(step["trace_id"] == accepted["trace_id"] for step in agent_trace)
            assert all(step["venue_id"] == "west-lake-park" for step in agent_trace)
            assert all(step["session_id"] == accepted["session_id"] for step in agent_trace)

            app.state.test_principal = {**app.state.test_principal, "role": "manager"}
            llm_calls_response = await client.get(
                "/api/v1/admin/llm-calls",
                params={"trace_id": accepted["trace_id"]},
            )
            assert llm_calls_response.status_code == 200
            llm_calls = llm_calls_response.json()["llm_calls"]
            assert {call["agent_id"] for call in llm_calls} == {
                "ContextTrigger",
                "Router",
                "MemoryOps",
                "Commander",
            }
            assert all(call["agent_name"] for call in llm_calls)
            assert all(call["venue_id"] == "west-lake-park" for call in llm_calls)

            events_response = await client.get("/api/v1/admin/events")
            assert events_response.status_code == 200
            events = events_response.json()["events"]
            live_event = next(event for event in events if event["trace_id"] == accepted["trace_id"])
            assert live_event["push_id"] == accepted["message_id"]
            assert live_event["source_type"] == "LIVE"
            assert live_event["venue_id"] == "west-lake-park"
            assert live_event["status"] == "OPEN"
            assert live_event["business_id"].startswith("SJ-")
            assert vector_store.upserts[0]["metadata"]["event_id"] == live_event["event_id"]

            assert internal_result["route"]["severity"] == "P1"
            cards = internal_result["business_cards"]
            event_card = next(card for card in cards if card["card_type"] == "event")
            sop_card = next(card for card in cards if card["card_type"] == "sop_reference")
            assert event_card["resource_id"] == live_event["event_id"]
            assert event_card["business_code"] == live_event["business_id"]
            assert event_card["severity_label"].startswith("P1")
            assert sop_card["title"] == "观光车雨后复运与异常异响处置"
            assert sop_card["version"] == "2.1"
            assert sop_card["source_id"] == "2101"
            assert sop_card["resource_id"] == "2101"
            assert sop_card["vector_doc_id"] == "sop:west-lake-park:2101"
            assert sop_card["status"] == "PUBLISHED"
            assert sop_card["publisher_name"] == "王敏"
            assert sop_card["published_at"] == 1785283200.0
            assert sop_card["employee_url"] == "/assistant/knowledge/sop/2101?version=2.1"
            source_sop = await db_client.fetch_one(
                "SELECT * FROM sop_documents WHERE id = ? AND venue_id = ?",
                (int(sop_card["source_id"]), "west-lake-park"),
            )
            assert source_sop["title"] == sop_card["title"]
            assert source_sop["version"] == sop_card["version"]
            assert source_sop["status"] == sop_card["status"]

            retrieval_snapshot = await db_client.fetch_one(
                "SELECT * FROM knowledge_retrieval_snapshots WHERE trace_id = ? AND venue_id = ?",
                (accepted["trace_id"], "west-lake-park"),
            )
            assert retrieval_snapshot["status"] == "SUCCEEDED"
            assert retrieval_snapshot["message_id"] == accepted["message_id"]
            assert retrieval_snapshot["session_id"] == accepted["session_id"]
            assert retrieval_snapshot["agent_id"] == "MemoryOps"
            assert retrieval_snapshot["raw_hit_count"] == 1
            assert retrieval_snapshot["selected_count"] == 1
            assert len(retrieval_snapshot["query_sha256"]) == 64
            attempts = json.loads(retrieval_snapshot["attempts_json"])
            assert attempts[0]["strategy"] == "semantic"
            assert attempts[0]["hits"][0]["vector_doc_id"] == "sop:west-lake-park:2101"
            assert attempts[0]["hits"][0]["selected"] is True
            references = json.loads(retrieval_snapshot["references_json"])
            assert references[0]["source_id"] == "2101"
            assert references[0]["version"] == "2.1"
            assert references[0]["status"] == "PUBLISHED"
            assert (
                internal_result["knowledge_result"]["structured_data"]
                ["retrieval_snapshot_id"]
                == retrieval_snapshot["id"]
            )

            trace_response = await client.get(
                f"/api/v1/admin/traces/{accepted['trace_id']}"
            )
            assert trace_response.status_code == 200, trace_response.text
            trace_payload = trace_response.json()
            assert trace_payload["summary"]["knowledge_retrievals"] == 1
            assert trace_payload["summary"]["knowledge_hits"] == 1
            assert {
                item["resource_id"]
                for item in trace_payload["timeline"]
                if item["kind"] == "KNOWLEDGE_RETRIEVAL"
            } == {retrieval_snapshot["id"]}
            app.state.push_writer.assert_not_awaited()
    finally:
        worker.stop()
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        await db_client.close()


@pytest.mark.asyncio
async def test_successful_wechat_push_writes_tenant_push_log(tmp_path, monkeypatch):
    app, db_client, _, worker = await build_golden_chain_app(
        tmp_path,
        monkeypatch,
        push_succeeds=True,
        use_real_push_logger=True,
    )
    worker_task = asyncio.create_task(worker.start())
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            accepted_response = await client.post(
                "/api/v1/messages/",
                json={
                    "content": "East gate escalator stopped with visitors stranded",
                    "session_id": "session-push-log",
                },
            )
            assert accepted_response.status_code == 202
            accepted = accepted_response.json()

            message_status = None
            for _ in range(100):
                status_response = await client.get(f"/api/v1/messages/{accepted['message_id']}")
                assert status_response.status_code == 200
                message_status = status_response.json()
                if message_status["status"] in {"COMPLETED", "FAILED"}:
                    break
                await asyncio.sleep(0.01)

            assert message_status["status"] == "COMPLETED"
            push_log = await db_client.fetch_one(
                "SELECT * FROM push_logs WHERE trace_id = ? AND venue_id = ?",
                (accepted["trace_id"], "west-lake-park"),
            )
            assert push_log is not None
            assert push_log["msg_id"] == accepted["message_id"]
            assert push_log["venue_id"] == "west-lake-park"
            assert push_log["from_user"] == "operator-golden-chain"
    finally:
        worker.stop()
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        await db_client.close()


@pytest.mark.asyncio
async def test_formal_message_intake_routes_memory_ops_with_venue_filtered_rag(tmp_path, monkeypatch):
    app, db_client, vector_store, worker = await build_golden_chain_app(
        tmp_path,
        monkeypatch,
        router_intent="emergency_advice",
    )
    worker_task = asyncio.create_task(worker.start())
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            accepted_response = await client.post(
                "/api/v1/messages/",
                json={
                    "content": "东门扶梯停运，请检索历史案例给出处置建议",
                    "session_id": "session-memory-ops",
                },
            )
            assert accepted_response.status_code == 202
            accepted = accepted_response.json()

            message_status = None
            for _ in range(100):
                status_response = await client.get(f"/api/v1/messages/{accepted['message_id']}")
                message_status = status_response.json()
                if message_status["status"] in {"COMPLETED", "FAILED"}:
                    break
                await asyncio.sleep(0.01)

            assert message_status["status"] == "COMPLETED"
            assert "target_agent" not in message_status
            assert "result" not in message_status
            internal_run = await MessageRunRepository(db_client).get(accepted["message_id"])
            assert internal_run["target_agent"] == "memory_ops"
            assert [step["agent_id"] for step in internal_run["result"]["agent_trace"]] == [
                "ContextTrigger",
                "Router",
                "MemoryOps",
            ]
            assert vector_store.queries == [
                {
                    "text": "东门扶梯停运，请检索历史案例给出处置建议",
                    "top_k": 8,
                    "threshold": 0.75,
                    "venue_id": "west-lake-park",
                }
            ]

            event = await db_client.fetch_one(
                "SELECT * FROM confirmed_events WHERE trace_id = ? AND venue_id = ?",
                (accepted["trace_id"], "west-lake-park"),
            )
            assert event["source_type"] == "LIVE"
            assert event["push_id"] == accepted["message_id"]
            llm_calls = await db_client.fetch_all(
                "SELECT agent_id, agent_name FROM llm_call_logs WHERE trace_id = ?",
                (accepted["trace_id"],),
            )
            assert {row["agent_id"] for row in llm_calls} == {
                "ContextTrigger",
                "Router",
                "MemoryOps",
            }
            assert all(row["agent_name"] for row in llm_calls)
    finally:
        worker.stop()
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        await db_client.close()


@pytest.mark.asyncio
async def test_unified_assistant_uses_authorized_experience_via_persona_and_records_usage(
    tmp_path,
    monkeypatch,
):
    app, db_client, _, worker = await build_golden_chain_app(
        tmp_path,
        monkeypatch,
        router_intent="emergency_advice",
        retrieval_vector_store_factory=SopAndAuthorizedExperienceVectorStore,
    )
    await seed_authorized_experience(db_client)

    worker_task = asyncio.create_task(worker.start())
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            accepted_response = await client.post(
                "/api/v1/messages/",
                json={
                    "content": "7号车晨检有随车速变化的轻微金属擦声，踩刹车时没变大，也没有发热和焦味，能直接载客吗？",
                    "session_id": "session-authorized-experience",
                },
            )
            assert accepted_response.status_code == 202
            accepted = accepted_response.json()

            message_status = None
            for _ in range(100):
                status_response = await client.get(f"/api/v1/messages/{accepted['message_id']}")
                assert status_response.status_code == 200
                message_status = status_response.json()
                if message_status["status"] in {"COMPLETED", "FAILED"}:
                    break
                await asyncio.sleep(0.01)

            app.state.test_principal = {**app.state.test_principal, "role": "manager"}
            trace_response = await client.get(
                f"/api/v1/admin/traces/{accepted['trace_id']}"
            )
            assert trace_response.status_code == 200, trace_response.text
            trace_payload = trace_response.json()

        assert message_status["status"] == "COMPLETED"
        assert "result" not in message_status
        result = (await MessageRunRepository(db_client).get(accepted["message_id"]))["result"]
        assert [step["agent_id"] for step in result["agent_trace"]] == [
            "ContextTrigger",
            "Router",
            "MemoryOps",
            "Persona",
        ]
        assert result["agent_result"]["structured_data"]["response_mode"] == (
            "AUTHORIZED_EXPERIENCE_SYNTHESIS"
        )
        assert result["agent_result"]["structured_data"]["used_experience_card_ids"] == [
            "experience-card-1"
        ]
        assert "非专家本人实时回复" in message_status["reply_text"]

        cards = result["business_cards"]
        sop_card = next(card for card in cards if card["card_type"] == "sop_reference")
        experience_card = next(
            card for card in cards if card["card_type"] == "experience_reference"
        )
        assert sop_card["source_id"] == "2101"
        assert experience_card["source_id"] == "experience-card-1"
        assert experience_card["business_code"] == "JY-20260808-0001"
        assert experience_card["expert_name"] == "张建国"
        assert experience_card["status"] == "PUBLISHED"
        assert experience_card["source_event_business_id"] == "SJ-20260808-0001"
        assert "雨后晨检" in experience_card["applicable_context"]
        assert experience_card["authorization_scopes"] == [
            {"scope_type": "VENUE", "scope_value": "west-lake-park"}
        ]

        retrieval_snapshot_id = result["knowledge_result"]["structured_data"][
            "retrieval_snapshot_id"
        ]
        usage = await db_client.fetch_one(
            "SELECT * FROM experience_usage_logs WHERE card_id = ?",
            ("experience-card-1",),
        )
        assert usage["usage_type"] == "REFERENCED"
        assert usage["user_id"] == "operator-golden-chain"
        assert usage["session_id"] == accepted["session_id"]
        assert usage["message_id"] == accepted["message_id"]
        assert usage["trace_id"] == accepted["trace_id"]
        assert usage["retrieval_snapshot_id"] == retrieval_snapshot_id
        assert usage["experience_version"] == 1
        assert usage["idempotency_key"]

        assert trace_payload["summary"]["experience_usages"] == 1
        trace_usage = trace_payload["experience_usages"][0]
        assert trace_usage["business_id"] == "JY-20260808-0001"
        assert trace_usage["title"] == "雨后观光车轮端间歇性金属异响判断"
        assert trace_usage["expert_name"] == "张建国"
        assert trace_usage["version"] == 1
        assert trace_usage["source_event_business_id"] == "SJ-20260808-0001"
        assert "query_text" not in trace_usage
        assert "idempotency_key" not in trace_usage
        assert any(
            item["kind"] == "EXPERIENCE_USAGE"
            and item["resource_id"] == "JY-20260808-0001"
            for item in trace_payload["timeline"]
        )
        manager_message_run = trace_payload["message_run"]
        assert "target_agent" not in manager_message_run
        manager_result = manager_message_run["result"]
        assert "route" not in manager_result
        assert "agent_result" not in manager_result
        assert "knowledge_result" not in manager_result
        assert "agent_trace" not in manager_result
        assert manager_result["reply_text"] == message_status["reply_text"]
        assert manager_result["business_cards"]

        llm_calls = await db_client.fetch_all(
            "SELECT agent_id FROM llm_call_logs WHERE trace_id = ?",
            (accepted["trace_id"],),
        )
        assert {row["agent_id"] for row in llm_calls} == {
            "ContextTrigger",
            "Router",
            "MemoryOps",
            "Persona",
        }
    finally:
        worker.stop()
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        await db_client.close()


@pytest.mark.asyncio
async def test_usage_persistence_failure_prevents_untracked_experience_reply(
    tmp_path,
    monkeypatch,
):
    app, db_client, _, worker = await build_golden_chain_app(
        tmp_path,
        monkeypatch,
        router_intent="emergency_advice",
        retrieval_vector_store_factory=SopAndAuthorizedExperienceVectorStore,
    )
    await seed_authorized_experience(db_client)
    original_execute = db_client.execute

    async def fail_experience_usage(sql, parameters=()):
        if "INSERT INTO experience_usage_logs" in sql:
            raise RuntimeError("simulated usage ledger outage")
        return await original_execute(sql, parameters)

    monkeypatch.setattr(db_client, "execute", fail_experience_usage)
    worker_task = asyncio.create_task(worker.start())
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            accepted_response = await client.post(
                "/api/v1/messages/",
                json={
                    "content": "7号车雨后有轻微金属擦声，能直接载客吗？",
                    "session_id": "session-usage-ledger-outage",
                },
            )
            assert accepted_response.status_code == 202
            accepted = accepted_response.json()

            message_status = None
            for _ in range(100):
                status_response = await client.get(f"/api/v1/messages/{accepted['message_id']}")
                assert status_response.status_code == 200
                message_status = status_response.json()
                if message_status["status"] in {
                    "COMPLETED",
                    "FAILED",
                    "RETRY_REQUIRED",
                }:
                    break
                await asyncio.sleep(0.01)

        assert message_status["status"] == "RETRY_REQUIRED"
        assert "无法完成审计" in message_status["reply_text"]
        assert "result" not in message_status
        result = (await MessageRunRepository(db_client).get(accepted["message_id"]))["result"]
        assert [step["agent_id"] for step in result["agent_trace"]][-2:] == [
            "MemoryOps",
            "Persona",
        ]
        assert not result.get("business_cards")
        assert await db_client.fetch_one(
            "SELECT id FROM experience_usage_logs WHERE card_id = ?",
            ("experience-card-1",),
        ) is None
    finally:
        worker.stop()
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        await db_client.close()


@pytest.mark.asyncio
async def test_vector_hit_without_explicit_authorization_never_invokes_persona(
    tmp_path,
    monkeypatch,
):
    app, db_client, _, worker = await build_golden_chain_app(
        tmp_path,
        monkeypatch,
        router_intent="emergency_advice",
        retrieval_vector_store_factory=SopAndAuthorizedExperienceVectorStore,
    )
    await seed_authorized_experience(db_client, authorize=False)
    worker_task = asyncio.create_task(worker.start())
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            accepted_response = await client.post(
                "/api/v1/messages/",
                json={
                    "content": "7号车雨后有轻微金属擦声，能直接载客吗？",
                    "session_id": "session-unauthorized-experience",
                },
            )
            assert accepted_response.status_code == 202
            accepted = accepted_response.json()

            message_status = None
            for _ in range(100):
                status_response = await client.get(f"/api/v1/messages/{accepted['message_id']}")
                assert status_response.status_code == 200
                message_status = status_response.json()
                if message_status["status"] in {"COMPLETED", "FAILED"}:
                    break
                await asyncio.sleep(0.01)

        assert message_status["status"] == "COMPLETED"
        assert "result" not in message_status
        result = (await MessageRunRepository(db_client).get(accepted["message_id"]))["result"]
        assert [step["agent_id"] for step in result["agent_trace"]] == [
            "ContextTrigger",
            "Router",
            "MemoryOps",
        ]
        assert any(card["card_type"] == "sop_reference" for card in result["business_cards"])
        assert not any(
            card["card_type"] == "experience_reference"
            for card in result["business_cards"]
        )
        assert await db_client.fetch_one(
            "SELECT id FROM experience_usage_logs WHERE card_id = ?",
            ("experience-card-1",),
        ) is None

        snapshot = await db_client.fetch_one(
            "SELECT attempts_json FROM knowledge_retrieval_snapshots WHERE trace_id = ?",
            (accepted["trace_id"],),
        )
        hits = [
            hit
            for attempt in json.loads(snapshot["attempts_json"])
            for hit in attempt["hits"]
        ]
        rejected = next(hit for hit in hits if hit["source_type"] == "EXPERIENCE_CARD")
        assert rejected["rejection_reason"] == "NOT_AUTHORIZED"
        llm_calls = await db_client.fetch_all(
            "SELECT agent_id FROM llm_call_logs WHERE trace_id = ?",
            (accepted["trace_id"],),
        )
        assert "Persona" not in {row["agent_id"] for row in llm_calls}
    finally:
        worker.stop()
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        await db_client.close()


@pytest.mark.parametrize(
    (
        "vector_store_factory",
        "expected_status",
        "expected_snapshot_status",
        "expected_notice",
        "forbidden_notice",
    ),
    [
        pytest.param(
            UnavailableVectorStore,
            "FAILED",
            "FAILED",
            "不可用",
            "尚未找到",
            id="chroma-query-failure",
        ),
        pytest.param(
            lambda: None,
            "FAILED",
            "FAILED",
            "不可用",
            "尚未找到",
            id="vector-client-missing",
        ),
        pytest.param(
            EmptyVectorStore,
            "SUCCEEDED",
            "ZERO_HITS",
            "尚未找到",
            "不可用",
            id="healthy-zero-hits",
        ),
        pytest.param(
            DraftSopVectorStore,
            "SUCCEEDED",
            "ZERO_HITS",
            "尚未找到",
            "不可用",
            id="unpublished-sop-is-not-a-hit",
        ),
    ],
)
@pytest.mark.asyncio
async def test_incident_message_distinguishes_knowledge_outage_from_zero_hits(
    tmp_path,
    monkeypatch,
    vector_store_factory,
    expected_status,
    expected_snapshot_status,
    expected_notice,
    forbidden_notice,
):
    app, db_client, _, worker = await build_golden_chain_app(
        tmp_path,
        monkeypatch,
        retrieval_vector_store_factory=vector_store_factory,
    )
    worker_task = asyncio.create_task(worker.start())
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            accepted_response = await client.post(
                "/api/v1/messages/",
                json={
                    "content": "East gate escalator stopped with visitors stranded",
                    "session_id": "session-knowledge-outage",
                },
            )
            assert accepted_response.status_code == 202
            accepted = accepted_response.json()

            message_status = None
            for _ in range(100):
                status_response = await client.get(f"/api/v1/messages/{accepted['message_id']}")
                assert status_response.status_code == 200
                message_status = status_response.json()
                if message_status["status"] in {"COMPLETED", "FAILED"}:
                    break
                await asyncio.sleep(0.01)

            assert message_status["status"] == "COMPLETED"
            assert "result" not in message_status
            internal_result = (
                await MessageRunRepository(db_client).get(accepted["message_id"])
            )["result"]
            memory_step = next(
                step
                for step in internal_result["agent_trace"]
                if step["agent_id"] == "MemoryOps"
            )
            assert memory_step["status"] == expected_status

            cards = internal_result["business_cards"]
            assert not any(
                card["card_type"]
                in {"sop_reference", "case_reference", "experience_reference"}
                for card in cards
            )
            knowledge_notice = next(
                card for card in cards if card["card_type"] == "knowledge_notice"
            )
            assert expected_notice in knowledge_notice["summary"]
            assert forbidden_notice not in knowledge_notice["summary"]
            assert "虚假" in knowledge_notice["summary"]

            snapshot = await db_client.fetch_one(
                """
                SELECT * FROM knowledge_retrieval_snapshots
                WHERE venue_id = ? AND trace_id = ?
                """,
                ("west-lake-park", accepted["trace_id"]),
            )
            assert snapshot["status"] == expected_snapshot_status
            assert snapshot["selected_count"] == 0
            assert json.loads(snapshot["references_json"]) == []
            assert (
                internal_result["knowledge_result"]["structured_data"]
                ["retrieval_snapshot_id"]
                == snapshot["id"]
            )
            attempts = json.loads(snapshot["attempts_json"])
            if expected_snapshot_status == "ZERO_HITS":
                assert [attempt["strategy"] for attempt in attempts] == ["semantic", "broad"]
            else:
                assert snapshot["error_type"]
                assert "sk-" not in (snapshot["error_message"] or "").lower()
                assert attempts[0]["status"] == "FAILED"
    finally:
        worker.stop()
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        await db_client.close()


@pytest.mark.asyncio
async def test_free_text_message_is_accepted_with_traceable_queue_payload(tmp_path):
    app, queue, db_client = await build_test_app(tmp_path)

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/messages/",
            json={
                "content": "东门检票口有游客晕倒，请立即处置",
                "metadata": {"venue_id": "west-lake-park"},
            },
        )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "QUEUED"
    assert body["message_id"]
    assert body["trace_id"]

    queued = queue.get_nowait()
    assert queued["msg_id"] == body["message_id"]
    assert queued["trace_id"] == body["trace_id"]
    assert queued["from_user"] == "operator-test"
    assert queued["venue_id"] == "west-lake-park"
    assert queued["content"] == "东门检票口有游客晕倒，请立即处置"

    audit = await db_client.fetch_one(
        "SELECT * FROM audit_logs WHERE trace_id = ? AND action = ?",
        (body["trace_id"], "MESSAGE_RUN_CREATED"),
    )
    assert audit is not None
    assert audit["venue_id"] == "west-lake-park"
    assert audit["user_id"] == "operator-test"
    assert audit["resource_type"] == "message_run"
    assert audit["resource_id"] == body["message_id"]
    assert audit["outcome"] == "SUCCEEDED"
    await db_client.close()


@pytest.mark.asyncio
async def test_message_is_not_queued_when_required_audit_cannot_be_written(tmp_path, monkeypatch):
    app, queue, db_client = await build_test_app(tmp_path)
    monkeypatch.setattr(
        "src.memory_palace.api.v1.endpoints.messages.write_audit",
        AsyncMock(side_effect=RuntimeError("audit unavailable")),
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/messages/",
                json={"content": "北门闸机故障，需要现场处置"},
            )

        assert response.status_code == 503
        assert response.json()["detail"] == "消息审计记录失败"
        assert queue.empty()
        run = await db_client.fetch_one("SELECT status, error FROM message_runs")
        assert run == {"status": "FAILED", "error": "消息审计记录失败"}
    finally:
        await db_client.close()


@pytest.mark.asyncio
async def test_real_wechat_gateway_is_disabled_even_with_complete_credentials(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr("src.memory_palace.core.gateway.get_wx_crypto", lambda: None)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("WECHAT_ALLOW_PLAINTEXT", "true")
    for key, value in {
        "WECHAT_TOKEN": "test-token",
        "WECHAT_ENCODING_AES_KEY": "a" * 43,
        "WECHAT_CORP_ID": "corp-west",
        "WECHAT_CORP_SECRET": "test-corp-secret",
        "WECHAT_AGENT_ID": "1000002",
    }.items():
        monkeypatch.setenv(key, value)
    queue = AsyncOnlyQueue()
    app, db_client = await build_wechat_gateway_app(tmp_path, queue)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    xml = """
    <xml>
      <ToUserName>corp-west</ToUserName>
      <FromUserName>operator-wechat</FromUserName>
      <CreateTime>1700000000</CreateTime>
      <MsgType>text</MsgType>
      <Content>南门扶梯突然停运，请安排现场处置</Content>
      <MsgId>wx-message-001</MsgId>
    </xml>
    """
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/webhook/v1/wechat", content=xml)
            duplicate = await client.post("/webhook/v1/wechat", content=xml)

        assert response.status_code == 503
        assert response.text == "integration disabled"
        assert duplicate.status_code == 503
        assert duplicate.text == "integration disabled"
        assert queue.messages == []
        assert await db_client.fetch_one("SELECT COUNT(*) AS total FROM message_runs") == {
            "total": 0
        }
    finally:
        await db_client.close()


@pytest.mark.asyncio
async def test_real_wechat_gateway_rejects_before_queue_access(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr("src.memory_palace.core.gateway.get_wx_crypto", lambda: None)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("WECHAT_ALLOW_PLAINTEXT", "true")
    for key, value in {
        "WECHAT_TOKEN": "test-token",
        "WECHAT_ENCODING_AES_KEY": "a" * 43,
        "WECHAT_CORP_ID": "corp-west",
        "WECHAT_CORP_SECRET": "test-corp-secret",
        "WECHAT_AGENT_ID": "1000002",
    }.items():
        monkeypatch.setenv(key, value)
    app, db_client = await build_wechat_gateway_app(tmp_path, AsyncOnlyQueue(fail=True))
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    xml = """
    <xml>
      <ToUserName>corp-west</ToUserName>
      <FromUserName>operator-wechat</FromUserName>
      <CreateTime>1700000001</CreateTime>
      <MsgType>text</MsgType>
      <Content>北门闸机网络中断</Content>
      <MsgId>wx-message-002</MsgId>
    </xml>
    """
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/webhook/v1/wechat", content=xml)

        assert response.status_code == 503
        assert response.text == "integration disabled"
        assert await db_client.fetch_one("SELECT COUNT(*) AS total FROM message_runs") == {
            "total": 0
        }
    finally:
        await db_client.close()


@pytest.mark.asyncio
async def test_wechat_gateway_is_disabled_when_crypto_is_not_configured(monkeypatch):
    monkeypatch.setattr("src.memory_palace.core.gateway.get_wx_crypto", lambda: None)
    monkeypatch.delenv("WECHAT_ALLOW_PLAINTEXT", raising=False)
    for key in (
        "WECHAT_TOKEN",
        "WECHAT_ENCODING_AES_KEY",
        "WECHAT_CORP_ID",
        "WECHAT_CORP_SECRET",
        "WECHAT_AGENT_ID",
    ):
        monkeypatch.delenv(key, raising=False)
    queue = AsyncOnlyQueue()
    app = FastAPI()
    app.state.message_queue = queue
    app.include_router(wechat_router, prefix="/webhook")
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/webhook/v1/wechat",
            content="<xml><MsgType>text</MsgType><Content>test</Content></xml>",
        )

    assert response.status_code == 503
    assert response.text == "integration disabled"
    assert queue.messages == []


@pytest.mark.asyncio
async def test_accepted_message_status_is_observable_by_message_id(tmp_path):
    app, _, db_client = await build_test_app(tmp_path)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        accepted = await client.post(
            "/messages/",
            json={
                "content": "东门游客中心发现儿童走失",
                "user_id": "operator-02",
                "metadata": {"venue_id": "west-lake-park"},
            },
        )
        message_id = accepted.json()["message_id"]
        status_response = await client.get(f"/messages/{message_id}")

    assert status_response.status_code == 200
    body = status_response.json()
    assert body["message_id"] == message_id
    assert body["trace_id"] == accepted.json()["trace_id"]
    assert body["status"] == "QUEUED"
    assert body["venue_id"] == "west-lake-park"
    assert body["content"] == "东门游客中心发现儿童走失"
    assert "target_agent" not in body
    assert "result" not in body
    assert "dead_letter_id" not in body
    await db_client.close()


@pytest.mark.asyncio
async def test_message_status_isolated_by_authenticated_venue(tmp_path):
    app, _, db_client = await build_test_app(tmp_path)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        accepted = await client.post(
            "/messages/",
            json={"content": "设备间出现焦糊味", "user_id": "spoofed-user"},
        )
        message_id = accepted.json()["message_id"]
        app.state.test_principal = {
            **app.state.test_principal,
            "venue_id": "another-venue",
        }
        forbidden_lookup = await client.get(f"/messages/{message_id}")

    assert forbidden_lookup.status_code == 404
    await db_client.close()


@pytest.mark.asyncio
async def test_message_status_rejects_another_employee_in_same_venue(tmp_path):
    app, _, db_client = await build_test_app(tmp_path)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        accepted = await client.post(
            "/messages/",
            json={"content": "设备间出现焦糊味"},
        )
        message_id = accepted.json()["message_id"]
        app.state.test_principal = {
            **app.state.test_principal,
            "user_id": "operator-other",
            "username": "operator-other",
        }
        forbidden_lookup = await client.get(f"/messages/{message_id}")

    assert forbidden_lookup.status_code == 404
    await db_client.close()


@pytest.mark.asyncio
async def test_operator_message_status_omits_internal_agent_payload(tmp_path):
    app, _, db_client = await build_test_app(tmp_path)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        accepted = await client.post(
            "/messages/",
            json={"content": "设备间出现焦糊味"},
        )
        message_id = accepted.json()["message_id"]
        await db_client.execute(
            """
            UPDATE message_runs
            SET status = 'RETRY_REQUIRED', target_agent = 'commander',
                result_json = ?, dead_letter_id = 'dead-letter-private-001'
            WHERE message_id = ?
            """,
            (
                json.dumps(
                    {
                        "route": {"target_agent": "commander"},
                        "system_prompt": "internal-only",
                    }
                ),
                message_id,
            ),
        )
        status_response = await client.get(f"/messages/{message_id}")

    assert status_response.status_code == 200
    payload = status_response.json()
    assert payload["status"] == "RETRY_REQUIRED"
    assert payload["retryable"] is True
    assert "target_agent" not in payload
    assert "result" not in payload
    assert "dead_letter_id" not in payload
    await db_client.close()


@pytest.mark.asyncio
async def test_worker_completion_is_visible_through_message_status_api(tmp_path):
    app, queue, db_client = await build_test_app(tmp_path)

    class StubOrchestrator:
        async def dispatch(self, message):
            return {
                "status": "processed",
                "trace_id": message["trace_id"],
                "route": {"target_agent": "commander", "intent": "incident_report"},
                "reply_text": "已启动走失儿童应急处置流程",
                "agent_result": {"action_taken": "commander_dispatched"},
            }

    container = SimpleNamespace(db_client=db_client, wechat_client=None)
    worker = MessageQueueWorker(queue=queue, concurrency=1, orchestrator=StubOrchestrator(), container=container)
    worker_task = asyncio.create_task(worker.start())
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            accepted = await client.post(
                "/messages/",
                json={
                    "content": "东门游客中心发现儿童走失",
                    "user_id": "operator-02",
                    "metadata": {"venue_id": "west-lake-park"},
                },
            )
            message_id = accepted.json()["message_id"]

            body = None
            for _ in range(50):
                status_response = await client.get(f"/messages/{message_id}")
                body = status_response.json()
                if body["status"] == "COMPLETED":
                    break
                await asyncio.sleep(0.01)

        assert body["status"] == "COMPLETED"
        assert body["reply_text"] == "已启动走失儿童应急处置流程"
        assert "target_agent" not in body
        assert "result" not in body
        internal_run = await MessageRunRepository(db_client).get(message_id)
        assert internal_run["target_agent"] == "commander"
        assert internal_run["result"]["trace_id"] == accepted.json()["trace_id"]
        assert body["processed_at"] is not None
    finally:
        worker.stop()
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        await db_client.close()


@pytest.mark.asyncio
async def test_workers_claim_retry_before_agent_execution_across_database_connections(
    tmp_path,
):
    database_path = tmp_path / "atomic-message-claim.db"
    first_db = AsyncDBClient(database_path)
    await init_database(first_db)
    second_db = AsyncDBClient(database_path)
    repository = MessageRunRepository(first_db)
    await repository.create(
        message_id="message-atomic-claim-01",
        trace_id="trace-atomic-claim-01",
        session_id="session-atomic-claim-01",
        user_id="operator-atomic-claim-01",
        venue_id="venue-atomic-claim-01",
        content="处理同一条重试消息",
    )
    await repository.mark_retrying(
        "message-atomic-claim-01",
        "上一次处理暂时失败，正在自动重试。",
    )

    agent_started = asyncio.Event()
    release_agent = asyncio.Event()

    class SlowOrchestrator:
        def __init__(self):
            self.calls = 0

        async def dispatch(self, message):
            self.calls += 1
            agent_started.set()
            await release_agent.wait()
            return {
                "status": "processed",
                "trace_id": message["trace_id"],
                "route": {"target_agent": "commander"},
                "reply_text": "已处理。",
            }

    orchestrator = SlowOrchestrator()
    first_queue = asyncio.Queue()
    second_queue = asyncio.Queue()
    first_worker = MessageQueueWorker(
        queue=first_queue,
        concurrency=1,
        orchestrator=orchestrator,
        container=SimpleNamespace(db_client=first_db, wechat_client=None),
    )
    second_worker = MessageQueueWorker(
        queue=second_queue,
        concurrency=1,
        orchestrator=orchestrator,
        container=SimpleNamespace(db_client=second_db, wechat_client=None),
    )
    first_worker_task = asyncio.create_task(first_worker.start())
    second_worker_task = asyncio.create_task(second_worker.start())
    message = {
        "msg_id": "message-atomic-claim-01",
        "trace_id": "trace-atomic-claim-01",
        "from_user": "operator-atomic-claim-01",
        "venue_id": "venue-atomic-claim-01",
        "msg_type": "text",
        "content": "处理同一条重试消息",
        "timestamp": time.time(),
        "_retries": 1,
    }

    try:
        await first_queue.put(dict(message))
        await asyncio.wait_for(agent_started.wait(), timeout=1)

        await second_queue.put(dict(message))
        await asyncio.wait_for(second_queue.join(), timeout=0.5)

        assert orchestrator.calls == 1
        processing = await repository.get("message-atomic-claim-01")
        assert processing["status"] == "PROCESSING"
        assert processing["attempt_count"] == 1

        release_agent.set()
        await asyncio.wait_for(first_queue.join(), timeout=1)
        completed = await repository.get("message-atomic-claim-01")
        assert completed["status"] == "COMPLETED"
        assert completed["attempt_count"] == 1
        assert completed["reply_text"] == "已处理。"

        await second_queue.put({**message, "content": "重复消息不得覆盖胜者结果"})
        await asyncio.wait_for(second_queue.join(), timeout=0.5)
        unchanged = await repository.get("message-atomic-claim-01")
        assert orchestrator.calls == 1
        assert unchanged["status"] == "COMPLETED"
        assert unchanged["attempt_count"] == 1
        assert unchanged["reply_text"] == "已处理。"
    finally:
        release_agent.set()
        first_worker.stop()
        second_worker.stop()
        first_worker_task.cancel()
        second_worker_task.cancel()
        await asyncio.gather(
            first_worker_task,
            second_worker_task,
            return_exceptions=True,
        )
        await first_db.close()
        await second_db.close()


@pytest.mark.asyncio
async def test_recovered_incomplete_processing_run_reclaims_agent_execution(tmp_path):
    database = AsyncDBClient(tmp_path / "recovered-processing-claim.db")
    await init_database(database)
    repository = MessageRunRepository(database)
    await repository.create(
        message_id="message-recovered-processing-01",
        trace_id="trace-recovered-processing-01",
        session_id="session-recovered-processing-01",
        user_id="operator-recovered-processing-01",
        venue_id="venue-recovered-processing-01",
        content="恢复重启前尚未完成的处置",
    )
    await repository.mark_processing("message-recovered-processing-01")

    class RecoveryOrchestrator:
        def __init__(self):
            self.calls = 0

        async def dispatch(self, message):
            self.calls += 1
            return {
                "status": "processed",
                "trace_id": message["trace_id"],
                "route": {"target_agent": "commander"},
                "reply_text": "重启恢复后已完成。",
            }

    orchestrator = RecoveryOrchestrator()
    queue = asyncio.Queue()
    worker = MessageQueueWorker(
        queue=queue,
        concurrency=1,
        orchestrator=orchestrator,
        container=SimpleNamespace(db_client=database, wechat_client=None),
    )
    worker_task = asyncio.create_task(worker.start())

    try:
        await queue.put(
            {
                "msg_id": "message-recovered-processing-01",
                "trace_id": "trace-recovered-processing-01",
                "session_id": "session-recovered-processing-01",
                "from_user": "operator-recovered-processing-01",
                "venue_id": "venue-recovered-processing-01",
                "msg_type": "text",
                "content": "恢复重启前尚未完成的处置",
                "timestamp": time.time(),
                "_recovered": True,
            }
        )
        await asyncio.wait_for(queue.join(), timeout=1)

        completed = await repository.get("message-recovered-processing-01")
        assert orchestrator.calls == 1
        assert completed["status"] == "COMPLETED"
        assert completed["attempt_count"] == 2
        assert completed["reply_text"] == "重启恢复后已完成。"
    finally:
        worker.stop()
        worker_task.cancel()
        await asyncio.gather(worker_task, return_exceptions=True)
        await database.close()


@pytest.mark.asyncio
async def test_worker_agent_failure_is_visible_through_message_status_api(tmp_path):
    app, queue, db_client = await build_test_app(tmp_path)

    class StubOrchestrator:
        async def dispatch(self, message):
            return {
                "status": "failed",
                "trace_id": message["trace_id"],
                "route": {"target_agent": "commander", "intent": "incident_report"},
                "reply_text": "系统正忙，请稍后再试。",
                "error": "DeepSeek authentication failed",
            }

    container = SimpleNamespace(db_client=db_client, wechat_client=None)
    worker = MessageQueueWorker(queue=queue, concurrency=1, orchestrator=StubOrchestrator(), container=container)
    worker_task = asyncio.create_task(worker.start())
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            accepted = await client.post(
                "/messages/",
                json={"content": "东门游客晕倒"},
            )
            message_id = accepted.json()["message_id"]

            body = None
            for _ in range(50):
                status_response = await client.get(f"/messages/{message_id}")
                body = status_response.json()
                if body["status"] == "RETRY_REQUIRED":
                    break
                await asyncio.sleep(0.01)

        assert body["status"] == "RETRY_REQUIRED"
        assert body["reply_text"] == "系统正忙，请稍后再试。"
        assert body["error"] == "任务处理鉴权失败，请检查依赖服务凭据后重试。"
        assert "target_agent" not in body
        assert "result" not in body
        assert "dead_letter_id" not in body
        assert "DeepSeek authentication failed" not in json.dumps(
            body,
            ensure_ascii=False,
        )
        assert body["attempt_count"] == 1
        assert body["retryable"] is True
        assert body["processed_at"] is not None
    finally:
        worker.stop()
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        await db_client.close()


@pytest.mark.asyncio
async def test_worker_acknowledges_successful_redis_stream_message():
    class RedisLikeQueue:
        def __init__(self):
            self._queue = asyncio.Queue()
            self.acked = []

        async def put(self, message):
            await self._queue.put(message)

        async def get(self):
            message = await self._queue.get()
            return {**message, "_redis_msg_id": "1700000000000-0"}

        def task_done(self):
            self._queue.task_done()

        def qsize(self):
            return self._queue.qsize()

        def empty(self):
            return self._queue.empty()

        async def ack(self, redis_message_id):
            self.acked.append(redis_message_id)

    class StubOrchestrator:
        async def dispatch(self, message):
            return {"status": "processed", "trace_id": message["trace_id"], "route": {}}

    queue = RedisLikeQueue()
    worker = MessageQueueWorker(
        queue=queue,
        queue_backend=queue,
        concurrency=1,
        orchestrator=StubOrchestrator(),
    )
    worker_task = asyncio.create_task(worker.start())

    try:
        await queue.put(
            {
                "msg_id": "message-redis-01",
                "trace_id": "trace-redis-01",
                "from_user": "operator-01",
                "msg_type": "text",
                "content": "设备故障",
                "timestamp": 1.0,
            }
        )
        for _ in range(50):
            if queue.acked:
                break
            await asyncio.sleep(0.01)

        assert queue.acked == ["1700000000000-0"]
    finally:
        worker.stop()
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_worker_drain_waits_for_inflight_message_before_shutdown():
    queue = asyncio.Queue()
    started = asyncio.Event()
    release = asyncio.Event()

    class SlowOrchestrator:
        async def dispatch(self, message):
            started.set()
            await release.wait()
            return {"status": "processed", "trace_id": message["trace_id"], "route": {}}

    worker = MessageQueueWorker(queue=queue, concurrency=1, orchestrator=SlowOrchestrator())
    worker_task = asyncio.create_task(worker.start())

    try:
        await queue.put(
            {
                "msg_id": "message-drain-01",
                "trace_id": "trace-drain-01",
                "from_user": "operator-01",
                "msg_type": "text",
                "content": "请生成今日待办",
                "timestamp": time.time(),
                "metadata": {"channel": "WEB"},
            }
        )
        await asyncio.wait_for(started.wait(), timeout=1)

        drain_task = asyncio.create_task(worker.drain(timeout=1))
        await asyncio.sleep(0)
        assert not drain_task.done()

        release.set()
        assert await drain_task is True
    finally:
        worker.stop()
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_simulator_reply_never_uses_real_wechat_delivery_client():
    queue = asyncio.Queue()

    class StubOrchestrator:
        async def dispatch(self, message):
            return {
                "status": "processed",
                "trace_id": message["trace_id"],
                "route": {"target_agent": "commander"},
                "reply_text": "已受理并开始分析。",
            }

    wechat_client = SimpleNamespace(send_text=AsyncMock())
    container = SimpleNamespace(db_client=None, wechat_client=wechat_client)
    worker = MessageQueueWorker(
        queue=queue,
        concurrency=1,
        orchestrator=StubOrchestrator(),
        container=container,
    )
    worker_task = asyncio.create_task(worker.start())

    try:
        await queue.put(
            {
                "msg_id": "message-simulator-01",
                "trace_id": "trace-simulator-01",
                "from_user": "operator-01",
                "msg_type": "text",
                "content": "12号车右后轮出现异响",
                "timestamp": time.time(),
                "metadata": {
                    "channel": "WECOM_SIMULATOR",
                    "external_user_id": "sim-operator-01",
                },
            }
        )
        await asyncio.wait_for(queue.join(), timeout=1)

        wechat_client.send_text.assert_not_awaited()
    finally:
        worker.stop()
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_real_wecom_delivery_is_disabled_by_policy(tmp_path):
    db_client = AsyncDBClient(tmp_path / "wecom-delivery-failure.db")
    await init_database(db_client)
    repository = MessageRunRepository(db_client)
    await repository.create(
        message_id="message-wecom-delivery-01",
        trace_id="trace-wecom-delivery-01",
        session_id="session-wecom-delivery-01",
        user_id="operator-wecom-01",
        venue_id="venue-wecom-01",
        content="请确认车辆隔离状态",
    )

    class StubOrchestrator:
        def __init__(self):
            self.calls = 0

        async def dispatch(self, message):
            self.calls += 1
            return {
                "status": "processed",
                "trace_id": message["trace_id"],
                "route": {"target_agent": "commander"},
                "reply_text": "车辆隔离任务已创建，请现场确认。",
            }

    queue = asyncio.Queue()
    container = SimpleNamespace(db_client=db_client, wechat_client=None)
    orchestrator = StubOrchestrator()
    worker = MessageQueueWorker(
        queue=queue,
        concurrency=1,
        orchestrator=orchestrator,
        container=container,
    )
    worker_task = asyncio.create_task(worker.start())

    try:
        await queue.put(
            {
                "msg_id": "message-wecom-delivery-01",
                "trace_id": "trace-wecom-delivery-01",
                "session_id": "session-wecom-delivery-01",
                "from_user": "operator-wecom-01",
                "venue_id": "venue-wecom-01",
                "msg_type": "text",
                "content": "请确认车辆隔离状态",
                "timestamp": time.time(),
                "channel": "WECOM",
                "metadata": {
                    "channel": "WECOM",
                    "external_user_id": "wecom-operator-01",
                },
            }
        )
        await asyncio.wait_for(queue.join(), timeout=1)

        await assert_real_wecom_policy_rejection(
            repository,
            db_client,
            message_id="message-wecom-delivery-01",
            venue_id="venue-wecom-01",
        )
        assert orchestrator.calls == 0
    finally:
        worker.stop()
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        await db_client.close()


@pytest.mark.asyncio
async def test_structured_real_wecom_reply_is_rejected_without_client_calls(
    tmp_path,
):
    db_client = AsyncDBClient(tmp_path / "wecom-structured-delivery.db")
    await init_database(db_client)
    repository = MessageRunRepository(db_client)
    await repository.create(
        message_id="message-wecom-structured-01",
        trace_id="trace-wecom-structured-01",
        session_id="session-wecom-structured-01",
        user_id="operator-wecom-structured-01",
        venue_id="venue-wecom-structured-01",
        content="请创建并下发车辆隔离任务",
    )

    class StructuredResultOrchestrator:
        def __init__(self):
            self.calls = 0

        async def dispatch(self, message):
            self.calls += 1
            return {
                "status": "processed",
                "trace_id": message["trace_id"],
                "route": {"target_agent": "commander"},
                "reply_text": None,
                "business_cards": [
                    {
                        "card_type": "task",
                        "business_code": "RW-20260731-001",
                        "title": "复核 12 号车隔离状态",
                        "summary": "车辆已停车断电，等待现场负责人复核。",
                        "status": "PENDING",
                        "owner_name": "李明",
                        "next_action": "上传隔离照片并确认",
                        "employee_url": "/assistant/work/task/task-structured-01",
                        "api_key": "sk-must-not-be-delivered",
                    }
                ],
            }

    queue = asyncio.Queue()
    wechat_client = SimpleNamespace(
        send_markdown=AsyncMock(return_value=False),
        send_textcard=AsyncMock(return_value=False),
        send_text=AsyncMock(return_value=True),
    )
    container = SimpleNamespace(db_client=db_client, wechat_client=wechat_client)
    orchestrator = StructuredResultOrchestrator()
    worker = MessageQueueWorker(
        queue=queue,
        concurrency=1,
        orchestrator=orchestrator,
        container=container,
    )
    worker_task = asyncio.create_task(worker.start())

    try:
        await queue.put(
            {
                "msg_id": "message-wecom-structured-01",
                "trace_id": "trace-wecom-structured-01",
                "session_id": "session-wecom-structured-01",
                "from_user": "operator-wecom-structured-01",
                "venue_id": "venue-wecom-structured-01",
                "msg_type": "text",
                "content": "请创建并下发车辆隔离任务",
                "timestamp": time.time(),
                "channel": "WECOM",
                "metadata": {
                    "channel": "WECOM",
                    "external_user_id": "wecom-operator-structured-01",
                },
            }
        )
        await asyncio.wait_for(queue.join(), timeout=1)

        await assert_real_wecom_policy_rejection(
            repository,
            db_client,
            message_id="message-wecom-structured-01",
            venue_id="venue-wecom-structured-01",
            wechat_client=wechat_client,
        )
        assert orchestrator.calls == 0
    finally:
        worker.stop()
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        await db_client.close()


@pytest.mark.asyncio
async def test_real_wecom_delivery_is_not_retried(tmp_path):
    db_client = AsyncDBClient(tmp_path / "wecom-delivery-retry.db")
    await init_database(db_client)
    repository = MessageRunRepository(db_client)
    await repository.create(
        message_id="message-wecom-delivery-02",
        trace_id="trace-wecom-delivery-02",
        session_id="session-wecom-delivery-02",
        user_id="operator-wecom-02",
        venue_id="venue-wecom-02",
        content="请给我车辆隔离确认结果",
    )

    class CountingOrchestrator:
        def __init__(self):
            self.calls = 0

        async def dispatch(self, message):
            self.calls += 1
            return {
                "status": "processed",
                "trace_id": message["trace_id"],
                "route": {"target_agent": "commander"},
                "reply_text": "车辆已隔离，等待现场复核。",
            }

    class DeliveryRetryQueue:
        def __init__(self):
            self._queue = asyncio.Queue()
            self.sequence = 0
            self.acked = []

        async def put(self, message):
            await self._queue.put(dict(message))

        async def get(self):
            message = await self._queue.get()
            if "_redis_msg_id" not in message:
                self.sequence += 1
                message["_redis_msg_id"] = f"delivery-{self.sequence}"
            return message

        def task_done(self):
            self._queue.task_done()

        def qsize(self):
            return self._queue.qsize()

        async def ack(self, redis_message_id):
            self.acked.append(redis_message_id)

        async def retry(self, message, redis_message_id):
            await self.ack(redis_message_id)
            retried = {
                key: value
                for key, value in message.items()
                if key != "_redis_msg_id"
            }
            retried["_retries"] = int(message.get("_retries", 0)) + 1
            await self.put(retried)
            return f"delivery-retry-{retried['_retries']}"

    orchestrator = CountingOrchestrator()
    queue = DeliveryRetryQueue()
    wechat_client = SimpleNamespace(send_text=AsyncMock(side_effect=[False, True]))
    container = SimpleNamespace(db_client=db_client, wechat_client=wechat_client)
    worker = MessageQueueWorker(
        queue=queue,
        queue_backend=queue,
        concurrency=1,
        orchestrator=orchestrator,
        container=container,
    )
    worker_task = asyncio.create_task(worker.start())

    try:
        await queue.put(
            {
                "msg_id": "message-wecom-delivery-02",
                "trace_id": "trace-wecom-delivery-02",
                "session_id": "session-wecom-delivery-02",
                "from_user": "operator-wecom-02",
                "venue_id": "venue-wecom-02",
                "msg_type": "text",
                "content": "请给我车辆隔离确认结果",
                "timestamp": time.time(),
                "channel": "WECOM",
                "metadata": {
                    "channel": "WECOM",
                    "external_user_id": "wecom-operator-02",
                },
            }
        )
        await asyncio.wait_for(queue._queue.join(), timeout=1)

        message_run = await repository.get("message-wecom-delivery-02")
        deliveries = await db_client.fetch_all(
            """
            SELECT * FROM push_logs
            WHERE venue_id = ? AND channel = ? AND idempotency_key = ?
            """,
            (
                "venue-wecom-02",
                "WECOM_REPLY",
                "assistant-reply:message-wecom-delivery-02",
            ),
        )
        assert orchestrator.calls == 0
        wechat_client.send_text.assert_not_awaited()
        assert message_run["status"] == "FAILED"
        assert message_run["attempt_count"] == 0
        assert message_run["delivery_status"] == "DISABLED_BY_POLICY"
        assert len(deliveries) == 1
        assert deliveries[0]["delivery_status"] == "DISABLED_BY_POLICY"
        assert len(queue.acked) == 1
        assert queue._queue.empty()
    finally:
        worker.stop()
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        await db_client.close()


@pytest.mark.asyncio
async def test_wecom_delivery_does_not_resend_after_send_succeeds_but_receipt_persistence_fails(
    tmp_path,
):
    db_client = AsyncDBClient(tmp_path / "wecom-delivery-ambiguous.db")
    await init_database(db_client)
    repository = MessageRunRepository(db_client)
    await repository.create(
        message_id="message-wecom-delivery-ambiguous-01",
        trace_id="trace-wecom-delivery-ambiguous-01",
        session_id="session-wecom-delivery-ambiguous-01",
        user_id="operator-wecom-ambiguous-01",
        venue_id="venue-wecom-ambiguous-01",
        content="请发送车辆隔离确认",
    )

    send_completed = asyncio.Event()
    receipt_persistence_failed = asyncio.Event()

    class FailFirstReceiptPersistenceDatabase:
        def __init__(self):
            self.failed = False

        async def execute(self, sql, parameters=()):
            if (
                send_completed.is_set()
                and not self.failed
                and "UPDATE" in sql
                and "delivery_status" in sql
                and "DELIVERED" in parameters
            ):
                self.failed = True
                receipt_persistence_failed.set()
                raise RuntimeError("delivery receipt persistence unavailable")
            return await db_client.execute(sql, parameters)

        async def fetch_one(self, sql, parameters=()):
            return await db_client.fetch_one(sql, parameters)

        async def fetch_all(self, sql, parameters=()):
            return await db_client.fetch_all(sql, parameters)

    class ConfirmedSendClient:
        def __init__(self):
            self.calls = 0

        async def send_text(self, recipient, reply_text):
            self.calls += 1
            send_completed.set()
            return True

    class DeliveryRecoveryQueue:
        def __init__(self):
            self._queue = asyncio.Queue()
            self._sequence = 0
            self.acked = []
            self.dead_lettered = asyncio.Event()

        async def put(self, message):
            await self._queue.put(dict(message))

        async def get(self):
            message = await self._queue.get()
            if "_redis_msg_id" not in message:
                self._sequence += 1
                message["_redis_msg_id"] = f"ambiguous-delivery-{self._sequence}"
            return message

        def task_done(self):
            self._queue.task_done()

        def qsize(self):
            return self._queue.qsize()

        async def ack(self, redis_message_id):
            self.acked.append(redis_message_id)

        async def retry(self, message, redis_message_id):
            retried = {
                key: value
                for key, value in message.items()
                if key != "_redis_msg_id"
            }
            retried["_retries"] = int(message.get("_retries", 0)) + 1
            await self.put(retried)
            await self.ack(redis_message_id)
            return f"ambiguous-retry-{retried['_retries']}"

        async def dead_letter(self, message, error):
            self.dead_lettered.set()
            return "dead-letter-wecom-ambiguous-01"

    class SingleResultOrchestrator:
        def __init__(self):
            self.calls = 0

        async def dispatch(self, message):
            self.calls += 1
            return {
                "status": "processed",
                "trace_id": message["trace_id"],
                "route": {"target_agent": "commander"},
                "reply_text": "车辆已隔离，等待现场复核。",
            }

    database = FailFirstReceiptPersistenceDatabase()
    queue = DeliveryRecoveryQueue()
    orchestrator = SingleResultOrchestrator()
    wechat_client = ConfirmedSendClient()
    container = SimpleNamespace(db_client=database, wechat_client=wechat_client)
    worker = MessageQueueWorker(
        queue=queue,
        queue_backend=queue,
        concurrency=1,
        orchestrator=orchestrator,
        container=container,
    )
    worker_task = asyncio.create_task(worker.start())

    try:
        await queue.put(
            {
                "msg_id": "message-wecom-delivery-ambiguous-01",
                "trace_id": "trace-wecom-delivery-ambiguous-01",
                "session_id": "session-wecom-delivery-ambiguous-01",
                "from_user": "operator-wecom-ambiguous-01",
                "venue_id": "venue-wecom-ambiguous-01",
                "msg_type": "text",
                "content": "请发送车辆隔离确认",
                "timestamp": time.time(),
                "channel": "WECOM",
                "metadata": {
                    "channel": "WECOM",
                    "external_user_id": "wecom-operator-ambiguous-01",
                },
            }
        )
        await asyncio.wait_for(queue._queue.join(), timeout=1)

        message_run = await repository.get("message-wecom-delivery-ambiguous-01")
        delivery = await db_client.fetch_one(
            """
            SELECT * FROM push_logs
            WHERE venue_id = ? AND channel = ? AND idempotency_key = ?
            """,
            (
                "venue-wecom-ambiguous-01",
                "WECOM_REPLY",
                "assistant-reply:message-wecom-delivery-ambiguous-01",
            ),
        )
        assert orchestrator.calls == 0
        assert wechat_client.calls == 0
        assert receipt_persistence_failed.is_set() is False
        assert message_run["status"] == "FAILED"
        assert message_run["delivery_status"] == "DISABLED_BY_POLICY"
        assert delivery["delivery_status"] == "DISABLED_BY_POLICY"
        assert delivery["delivery_claim_token"] is None
        assert len(queue.acked) == 1
    finally:
        worker.stop()
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        await db_client.close()


@pytest.mark.asyncio
async def test_concurrent_wecom_workers_send_once_and_late_failure_cannot_downgrade_delivery(
    tmp_path,
):
    db_client = AsyncDBClient(tmp_path / "wecom-delivery-claim.db")
    await init_database(db_client)
    repository = MessageRunRepository(db_client)
    await repository.create(
        message_id="message-wecom-delivery-claim-01",
        trace_id="trace-wecom-delivery-claim-01",
        session_id="session-wecom-delivery-claim-01",
        user_id="operator-wecom-claim-01",
        venue_id="venue-wecom-claim-01",
        content="请发送唯一一条车辆隔离确认",
    )
    await repository.save_result(
        "message-wecom-delivery-claim-01",
        {
            "status": "processed",
            "trace_id": "trace-wecom-delivery-claim-01",
            "route": {"target_agent": "commander"},
            "reply_text": "车辆已隔离，等待现场复核。",
        },
    )

    send_started = asyncio.Event()
    release_send = asyncio.Event()

    class BlockingSendClient:
        def __init__(self):
            self.calls = 0

        async def send_text(self, recipient, reply_text):
            self.calls += 1
            send_started.set()
            await release_send.wait()
            return True

    class ConcurrentDeliveryQueue:
        def __init__(self):
            self._queue = asyncio.Queue()
            self.acked = []
            self.dead_lettered = asyncio.Event()

        async def put(self, message):
            await self._queue.put(dict(message))

        async def get(self):
            return await self._queue.get()

        def task_done(self):
            self._queue.task_done()

        def qsize(self):
            return self._queue.qsize()

        async def ack(self, redis_message_id):
            self.acked.append(redis_message_id)

        async def dead_letter(self, message, error):
            self.dead_lettered.set()
            return f"dead-letter-{message['_redis_msg_id']}"

    class MustNotRunOrchestrator:
        async def dispatch(self, message):
            raise AssertionError("Concurrent delivery must reuse the saved Agent result")

    queue = ConcurrentDeliveryQueue()
    wechat_client = BlockingSendClient()
    container = SimpleNamespace(db_client=db_client, wechat_client=wechat_client)
    worker = MessageQueueWorker(
        queue=queue,
        queue_backend=queue,
        concurrency=2,
        orchestrator=MustNotRunOrchestrator(),
        container=container,
    )
    worker_task = asyncio.create_task(worker.start())
    base_message = {
        "msg_id": "message-wecom-delivery-claim-01",
        "trace_id": "trace-wecom-delivery-claim-01",
        "session_id": "session-wecom-delivery-claim-01",
        "from_user": "operator-wecom-claim-01",
        "venue_id": "venue-wecom-claim-01",
        "msg_type": "text",
        "content": "请发送唯一一条车辆隔离确认",
        "timestamp": time.time(),
        "channel": "WECOM",
        "metadata": {
            "channel": "WECOM",
            "external_user_id": "wecom-operator-claim-01",
        },
        "_delivery_only": True,
        "_retries": 3,
    }

    try:
        await queue.put({**base_message, "_redis_msg_id": "claim-worker-01"})
        await queue.put({**base_message, "_redis_msg_id": "claim-worker-02"})
        await asyncio.wait_for(queue._queue.join(), timeout=1)

        message_run = await repository.get("message-wecom-delivery-claim-01")
        delivery = await db_client.fetch_one(
            """
            SELECT * FROM push_logs
            WHERE venue_id = ? AND channel = ? AND idempotency_key = ?
            """,
            (
                "venue-wecom-claim-01",
                "WECOM_REPLY",
                "assistant-reply:message-wecom-delivery-claim-01",
            ),
        )
        assert wechat_client.calls == 0
        assert send_started.is_set() is False
        assert queue.dead_lettered.is_set() is False
        assert message_run["status"] == "FAILED"
        assert message_run["delivery_status"] == "DISABLED_BY_POLICY"
        assert delivery["delivery_status"] == "DISABLED_BY_POLICY"
        assert delivery["delivery_claim_token"] is None
        assert sorted(queue.acked) == ["claim-worker-01", "claim-worker-02"]
    finally:
        release_send.set()
        worker.stop()
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        await db_client.close()


@pytest.mark.asyncio
async def test_delivered_reply_ledger_rejects_late_failure_writes(tmp_path):
    db_client = AsyncDBClient(tmp_path / "wecom-delivery-terminal.db")
    await init_database(db_client)
    repository = MessageRunRepository(db_client)
    await repository.create(
        message_id="message-wecom-delivery-terminal-01",
        trace_id="trace-wecom-delivery-terminal-01",
        session_id="session-wecom-delivery-terminal-01",
        user_id="operator-wecom-terminal-01",
        venue_id="venue-wecom-terminal-01",
        content="请发送终态确认",
    )
    await repository.mark_delivery(
        "message-wecom-delivery-terminal-01",
        "DELIVERED",
        delivered_at=1700000042.0,
    )
    await record_reply_delivery(
        message_id="message-wecom-delivery-terminal-01",
        trace_id="trace-wecom-delivery-terminal-01",
        venue_id="venue-wecom-terminal-01",
        user_id="operator-wecom-terminal-01",
        channel="WECOM",
        recipient="wecom-operator-terminal-01",
        reply_text="终态确认已送达。",
        delivery_status="DELIVERED",
        database=db_client,
    )

    try:
        await asyncio.gather(
            repository.mark_delivery(
                "message-wecom-delivery-terminal-01",
                "FAILED",
                error="late worker failure",
            ),
            record_reply_delivery(
                message_id="message-wecom-delivery-terminal-01",
                trace_id="trace-wecom-delivery-terminal-01",
                venue_id="venue-wecom-terminal-01",
                user_id="operator-wecom-terminal-01",
                channel="WECOM",
                recipient="wecom-operator-terminal-01",
                reply_text="终态确认已送达。",
                delivery_status="FAILED",
                delivery_error="late worker failure",
                database=db_client,
            ),
        )

        message_run = await repository.get("message-wecom-delivery-terminal-01")
        delivery = await db_client.fetch_one(
            """
            SELECT * FROM push_logs
            WHERE venue_id = ? AND channel = ? AND idempotency_key = ?
            """,
            (
                "venue-wecom-terminal-01",
                "WECOM_REPLY",
                "assistant-reply:message-wecom-delivery-terminal-01",
            ),
        )
        assert message_run["delivery_status"] == "DELIVERED"
        assert message_run["delivery_error"] is None
        assert message_run["delivered_at"] == 1700000042.0
        assert delivery["delivery_status"] == "DELIVERED"
        assert delivery["delivery_error"] is None
    finally:
        await db_client.close()


@pytest.mark.asyncio
async def test_recovered_real_wecom_delivery_stays_disabled_after_restart(tmp_path):
    db_client = AsyncDBClient(tmp_path / "wecom-delivery-recovery.db")
    await init_database(db_client)
    repository = MessageRunRepository(db_client)
    await repository.create(
        message_id="message-wecom-delivery-03",
        trace_id="trace-wecom-delivery-03",
        session_id="session-wecom-delivery-03",
        user_id="operator-wecom-03",
        venue_id="venue-wecom-03",
        content="恢复中不要重复创建处置任务",
    )
    await repository.mark_processing("message-wecom-delivery-03")
    await repository.save_result(
        "message-wecom-delivery-03",
        {
            "status": "processed",
            "trace_id": "trace-wecom-delivery-03",
            "route": {"target_agent": "commander"},
            "reply_text": "原任务已恢复，车辆仍保持隔离。",
        },
    )
    await repository.mark_delivery("message-wecom-delivery-03", "PENDING")

    class MustNotRunOrchestrator:
        def __init__(self):
            self.calls = 0

        async def dispatch(self, message):
            self.calls += 1
            raise AssertionError("Recovered delivery must not rerun the Agent chain")

    orchestrator = MustNotRunOrchestrator()
    queue = asyncio.Queue()
    wechat_client = SimpleNamespace(send_text=AsyncMock(return_value=True))
    container = SimpleNamespace(db_client=db_client, wechat_client=wechat_client)
    worker = MessageQueueWorker(
        queue=queue,
        concurrency=1,
        orchestrator=orchestrator,
        container=container,
    )
    worker_task = asyncio.create_task(worker.start())

    try:
        await queue.put(
            {
                "msg_id": "message-wecom-delivery-03",
                "trace_id": "trace-wecom-delivery-03",
                "session_id": "session-wecom-delivery-03",
                "from_user": "operator-wecom-03",
                "venue_id": "venue-wecom-03",
                "msg_type": "text",
                "content": "恢复中不要重复创建处置任务",
                "timestamp": time.time(),
                "channel": "WECOM",
                "metadata": {
                    "channel": "WECOM",
                    "external_user_id": "wecom-operator-03",
                },
                "_recovered": True,
            }
        )
        await asyncio.wait_for(queue.join(), timeout=1)

        message_run = await repository.get("message-wecom-delivery-03")
        assert orchestrator.calls == 0
        wechat_client.send_text.assert_not_awaited()
        assert message_run["status"] == "FAILED"
        assert message_run["attempt_count"] == 1
        assert message_run["delivery_status"] == "DISABLED_BY_POLICY"
    finally:
        worker.stop()
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        await db_client.close()


@pytest.mark.asyncio
async def test_delivery_schema_backfills_only_completed_polling_channels(tmp_path):
    db_client = AsyncDBClient(tmp_path / "delivery-schema-backfill.db")
    await init_database(db_client)
    insert_sql = """
        INSERT INTO message_runs (
            message_id, trace_id, session_id, user_id, venue_id, content,
            status, channel, created_at, updated_at, processed_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'COMPLETED', ?, ?, ?, ?)
    """
    for parameters in (
        (
                "legacy-web-completed",
                "trace-legacy-web-completed",
                "session-legacy-web",
                "operator-legacy-web",
                "venue-legacy",
                "旧 Web 完成消息",
                "WEB",
                1700000000.0,
                1700000010.0,
                1700000009.0,
        ),
        (
                "legacy-wecom-completed",
                "trace-legacy-wecom-completed",
                "session-legacy-wecom",
                "operator-legacy-wecom",
                "venue-legacy",
                "旧企微完成消息",
                "WECOM",
                1700000000.0,
                1700000010.0,
                1700000009.0,
        ),
    ):
        await db_client.execute(insert_sql, parameters)

    await init_database(db_client)

    web_run = await db_client.fetch_one(
        "SELECT delivery_status, delivered_at FROM message_runs WHERE message_id = ?",
        ("legacy-web-completed",),
    )
    wecom_run = await db_client.fetch_one(
        "SELECT delivery_status, delivered_at FROM message_runs WHERE message_id = ?",
        ("legacy-wecom-completed",),
    )
    assert web_run == {"delivery_status": "PERSISTED", "delivered_at": 1700000009.0}
    assert wecom_run == {"delivery_status": "PENDING", "delivered_at": None}
    await db_client.close()

    class RecordingPostgres:
        def __init__(self):
            self._pool = object()
            self.statements = []

        async def execute(self, sql, parameters=()):
            self.statements.append(sql)
            return 0

    postgres = RecordingPostgres()
    await init_database(postgres)
    postgres_ddl = "\n".join(postgres.statements)
    assert "message_runs ADD COLUMN IF NOT EXISTS delivery_status" in postgres_ddl
    assert "message_runs ADD COLUMN IF NOT EXISTS delivered_at" in postgres_ddl
    assert "push_logs ADD COLUMN IF NOT EXISTS delivery_claim_token" in postgres_ddl
    assert "push_logs ADD COLUMN IF NOT EXISTS delivery_claimed_at" in postgres_ddl
    assert "SET delivery_status = 'PERSISTED'" in postgres_ddl
    assert "'WEB', 'WECOM_SIMULATOR', 'LEGACY', ''" in postgres_ddl


@pytest.mark.asyncio
async def test_empty_real_wecom_reply_is_rejected_by_policy(tmp_path):
    db_client = AsyncDBClient(tmp_path / "wecom-empty-reply.db")
    await init_database(db_client)
    repository = MessageRunRepository(db_client)
    await repository.create(
        message_id="message-wecom-delivery-04",
        trace_id="trace-wecom-delivery-04",
        session_id="session-wecom-delivery-04",
        user_id="operator-wecom-04",
        venue_id="venue-wecom-04",
        content="请返回处置建议",
    )

    class EmptyReplyOrchestrator:
        async def dispatch(self, message):
            return {
                "status": "processed",
                "trace_id": message["trace_id"],
                "route": {"target_agent": "commander"},
                "reply_text": None,
            }

    queue = asyncio.Queue()
    wechat_client = SimpleNamespace(send_text=AsyncMock(return_value=True))
    container = SimpleNamespace(db_client=db_client, wechat_client=wechat_client)
    worker = MessageQueueWorker(
        queue=queue,
        concurrency=1,
        orchestrator=EmptyReplyOrchestrator(),
        container=container,
    )
    worker_task = asyncio.create_task(worker.start())

    try:
        await queue.put(
            {
                "msg_id": "message-wecom-delivery-04",
                "trace_id": "trace-wecom-delivery-04",
                "session_id": "session-wecom-delivery-04",
                "from_user": "operator-wecom-04",
                "venue_id": "venue-wecom-04",
                "msg_type": "text",
                "content": "请返回处置建议",
                "timestamp": time.time(),
                "channel": "WECOM",
                "metadata": {
                    "channel": "WECOM",
                    "external_user_id": "wecom-operator-04",
                },
            }
        )
        await asyncio.wait_for(queue.join(), timeout=1)

        await assert_real_wecom_policy_rejection(
            repository,
            db_client,
            message_id="message-wecom-delivery-04",
            venue_id="venue-wecom-04",
            wechat_client=wechat_client,
        )
    finally:
        worker.stop()
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        await db_client.close()


@pytest.mark.asyncio
async def test_worker_retries_failed_redis_messages_before_dead_lettering():
    class RedisLikeQueue:
        def __init__(self):
            self._queue = asyncio.Queue()
            self.sequence = 0
            self.acked = []
            self.retry_counts = []
            self.dead_letters = []

        async def put(self, message):
            self.sequence += 1
            await self._queue.put({**message, "_redis_msg_id": f"170000000000{self.sequence}-0"})

        async def get(self):
            return await self._queue.get()

        def task_done(self):
            self._queue.task_done()

        def qsize(self):
            return self._queue.qsize()

        async def ack(self, redis_message_id):
            self.acked.append(redis_message_id)

        async def retry(self, message, redis_message_id):
            retry_count = int(message.get("_retries", 0)) + 1
            self.retry_counts.append(retry_count)
            await self.ack(redis_message_id)
            await self.put({**message, "_retries": retry_count})

        async def dead_letter(self, message, error):
            self.dead_letters.append(
                {"message": dict(message), "error": error}
            )

    class FailingOrchestrator:
        def __init__(self):
            self.calls = 0

        async def dispatch(self, message):
            self.calls += 1
            raise RuntimeError("DeepSeek timeout")

    queue = RedisLikeQueue()
    orchestrator = FailingOrchestrator()
    worker = MessageQueueWorker(
        queue=queue,
        queue_backend=queue,
        concurrency=1,
        orchestrator=orchestrator,
    )
    worker_task = asyncio.create_task(worker.start())

    try:
        await queue.put(
            {
                "msg_id": "message-redis-retry-01",
                "trace_id": "trace-redis-retry-01",
                "from_user": "operator-01",
                "msg_type": "text",
                "content": "设备故障",
                "timestamp": time.time(),
            }
        )
        for _ in range(100):
            if queue.dead_letters:
                break
            await asyncio.sleep(0.01)

        assert orchestrator.calls == 4
        assert queue.retry_counts == [1, 2, 3]
        assert len(queue.dead_letters) == 1
        assert queue.dead_letters[0]["message"]["_retries"] == 3
        assert len(queue.acked) == 4
    finally:
        worker.stop()
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_transient_failure_stays_retrying_until_final_dead_letter(tmp_path):
    app, _, db_client = await build_test_app(tmp_path)

    class ControlledRedisQueue:
        def __init__(self):
            self._queue = asyncio.Queue()
            self._sequence = 0
            self._next_retry = None
            self.retry_ready = asyncio.Event()
            self.dead_lettered = asyncio.Event()
            self.acked = []

        async def put(self, message):
            await self._queue.put(dict(message))

        async def get(self):
            message = await self._queue.get()
            if "_redis_msg_id" not in message:
                self._sequence += 1
                message["_redis_msg_id"] = f"170000000010{self._sequence}-0"
            return message

        def task_done(self):
            self._queue.task_done()

        def qsize(self):
            return self._queue.qsize()

        async def ack(self, redis_message_id):
            self.acked.append(redis_message_id)

        async def retry(self, message, redis_message_id):
            await self.ack(redis_message_id)
            self._next_retry = {
                key: value
                for key, value in message.items()
                if key != "_redis_msg_id"
            }
            self._next_retry["_retries"] = int(message.get("_retries", 0)) + 1
            self.retry_ready.set()
            return f"retry-{self._next_retry['_retries']}"

        async def release_retry(self):
            next_retry = self._next_retry
            self._next_retry = None
            self.retry_ready.clear()
            await self.put(next_retry)

        async def dead_letter(self, message, error):
            self.dead_lettered.set()
            return "dead-letter-message-retry-01"

    class FailingOrchestrator:
        async def dispatch(self, message):
            raise RuntimeError("DeepSeek temporary timeout")

    queue = ControlledRedisQueue()
    set_message_queue(queue)
    container = SimpleNamespace(db_client=db_client, wechat_client=None)
    worker = MessageQueueWorker(
        queue=queue,
        queue_backend=queue,
        concurrency=1,
        orchestrator=FailingOrchestrator(),
        container=container,
    )
    worker_task = asyncio.create_task(worker.start())
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            accepted = await client.post(
                "/messages/",
                json={"content": "请把护板间隙检查整理成我的今日待办"},
            )
            message_id = accepted.json()["message_id"]

            for expected_attempt in (1, 2, 3):
                await asyncio.wait_for(queue.retry_ready.wait(), timeout=1)
                retrying = await client.get(f"/messages/{message_id}")
                assert retrying.status_code == 200
                retrying_body = retrying.json()
                assert retrying_body["status"] == "RETRYING"
                assert retrying_body["attempt_count"] == expected_attempt
                assert retrying_body["max_attempts"] == 4
                assert retrying_body["retryable"] is False
                await queue.release_retry()

            await asyncio.wait_for(queue.dead_lettered.wait(), timeout=1)
            final_body = None
            for _ in range(50):
                final_body = (await client.get(f"/messages/{message_id}")).json()
                if final_body["status"] == "RETRY_REQUIRED":
                    break
                await asyncio.sleep(0.01)

        assert final_body["status"] == "RETRY_REQUIRED"
        assert final_body["attempt_count"] == 4
        assert final_body["retryable"] is True
        assert "dead_letter_id" not in final_body
        internal_run = await MessageRunRepository(db_client).get(message_id)
        assert internal_run["dead_letter_id"] == "dead-letter-message-retry-01"
        assert len(queue.acked) == 4
    finally:
        worker.stop()
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        await db_client.close()


@pytest.mark.asyncio
async def test_final_dead_letter_keeps_redis_pending_when_retry_state_persistence_fails(
    tmp_path,
):
    db_client = AsyncDBClient(tmp_path / "dead-letter-persistence-failure.db")
    await init_database(db_client)
    repository = MessageRunRepository(db_client)
    await repository.create(
        message_id="message-dead-letter-persistence-01",
        trace_id="trace-dead-letter-persistence-01",
        session_id="session-dead-letter-persistence-01",
        user_id="operator-dead-letter-persistence-01",
        venue_id="venue-dead-letter-persistence-01",
        content="请处理设备故障",
    )

    persistence_failed = asyncio.Event()

    class FailingFinalStateDatabase:
        async def execute(self, sql, parameters=()):
            if "UPDATE message_runs" in sql and parameters and parameters[0] == "RETRY_REQUIRED":
                persistence_failed.set()
                raise RuntimeError("message run final state unavailable")
            return await db_client.execute(sql, parameters)

        async def fetch_one(self, sql, parameters=()):
            return await db_client.fetch_one(sql, parameters)

        async def fetch_all(self, sql, parameters=()):
            return await db_client.fetch_all(sql, parameters)

    class PendingAwareQueue:
        def __init__(self):
            self._queue = asyncio.Queue()
            self.acked = []
            self.dead_lettered = asyncio.Event()

        async def put(self, message):
            await self._queue.put(dict(message))

        async def get(self):
            return await self._queue.get()

        def task_done(self):
            self._queue.task_done()

        def qsize(self):
            return self._queue.qsize()

        async def ack(self, redis_message_id):
            self.acked.append(redis_message_id)

        async def dead_letter(self, message, error):
            self.dead_lettered.set()
            return "dead-letter-persistence-01"

    class FailingOrchestrator:
        async def dispatch(self, message):
            raise RuntimeError("DeepSeek temporary timeout")

    queue = PendingAwareQueue()
    container = SimpleNamespace(
        db_client=FailingFinalStateDatabase(),
        wechat_client=None,
    )
    worker = MessageQueueWorker(
        queue=queue,
        queue_backend=queue,
        concurrency=1,
        orchestrator=FailingOrchestrator(),
        container=container,
    )
    worker_task = asyncio.create_task(worker.start())

    try:
        await queue.put(
            {
                "msg_id": "message-dead-letter-persistence-01",
                "trace_id": "trace-dead-letter-persistence-01",
                "from_user": "operator-dead-letter-persistence-01",
                "venue_id": "venue-dead-letter-persistence-01",
                "msg_type": "text",
                "content": "请处理设备故障",
                "timestamp": time.time(),
                "_redis_msg_id": "1700000000200-0",
                "_retries": 3,
            }
        )
        await asyncio.wait_for(queue.dead_lettered.wait(), timeout=1)
        await asyncio.wait_for(persistence_failed.wait(), timeout=1)
        await asyncio.sleep(0)

        message_run = await repository.get("message-dead-letter-persistence-01")
        assert queue.acked == []
        assert message_run["status"] == "RETRYING"
        assert message_run["dead_letter_id"] is None
    finally:
        worker.stop()
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        await db_client.close()


@pytest.mark.asyncio
async def test_same_session_supplement_updates_explicit_open_event_without_duplicate(
    tmp_path,
    monkeypatch,
):
    app, db_client, _, worker = await build_golden_chain_app(tmp_path, monkeypatch)
    repository = MessageRunRepository(db_client)
    worker_task = asyncio.create_task(worker.start())
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async def send_and_wait(client, content, *, metadata=None):
        response = await client.post(
            "/api/v1/messages/",
            json={
                "content": content,
                "session_id": "session-event-supplement",
                "metadata": metadata or {},
            },
        )
        assert response.status_code == 202, response.text
        accepted = response.json()
        completed = None
        for _ in range(100):
            status_response = await client.get(
                f"/api/v1/messages/{accepted['message_id']}"
            )
            assert status_response.status_code == 200, status_response.text
            completed = status_response.json()
            if completed["status"] in {"COMPLETED", "FAILED"}:
                break
            await asyncio.sleep(0.01)
        assert completed["status"] == "COMPLETED", completed
        return accepted, completed

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first_accepted, first = await send_and_wait(
                client,
                "12号观光车右后轮有间歇性金属摩擦声，车辆已停运断电。",
            )
            first_result = (await repository.get(first_accepted["message_id"]))["result"]
            event_id = first_result["event_id"]
            assert event_id

            second_accepted, second = await send_and_wait(
                client,
                "补充信息：车辆位于东门维修区，右后轮内侧有水迹，现场无人受伤。",
                metadata={
                    "source_event_id": event_id,
                    "confirmed_location": "东门维修区",
                },
            )

            second_result = (await repository.get(second_accepted["message_id"]))[
                "result"
            ]
            assert second_result["event_id"] == event_id
            second_event_card = next(
                card
                for card in second_result["business_cards"]
                if card["card_type"] == "event"
            )
            assert second_event_card["resource_id"] == event_id

            app.state.test_principal = {**app.state.test_principal, "role": "manager"}
            events_response = await client.get("/api/v1/admin/events")
            detail_response = await client.get(f"/api/v1/admin/events/{event_id}")

        assert events_response.status_code == 200, events_response.text
        live_events = [
            event
            for event in events_response.json()["events"]
            if event["source_type"] == "LIVE"
        ]
        assert len(live_events) == 1
        assert live_events[0]["event_id"] == event_id
        assert "东门维修区" in live_events[0]["raw_text"]
        assert detail_response.status_code == 200, detail_response.text
        timeline = detail_response.json()["dossier"]["timeline"]
        updates = [
            entry
            for entry in timeline
            if entry["technical"]["activity_type"] == "EVENT_UPDATED"
        ]
        assert len(updates) == 1
        assert updates[0]["technical"]["message_id"] == second_accepted["message_id"]
        assert updates[0]["technical"]["session_id"] == first_accepted["session_id"]
    finally:
        worker.stop()
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        await db_client.close()
