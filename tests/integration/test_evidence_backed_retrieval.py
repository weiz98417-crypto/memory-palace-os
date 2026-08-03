import json
import traceback

import pytest

from src.memory_palace.core.trace_timeline import build_trace_timeline
from src.memory_palace.knowledge.db_client import AsyncDBClient
from src.memory_palace.knowledge.db_init import init_database
from src.memory_palace.knowledge.evidence_backed_retrieval import (
    EvidenceBackedKnowledgeRetriever,
    KnowledgeRetrievalError,
    KnowledgeSnapshotPersistenceError,
    RetrievalRequest,
)
from src.memory_palace.knowledge.experience_schema import init_experience_schema


class SopVectorStore:
    backend_mode = "test"

    def __init__(self, *, version="2.1", source_id="2101"):
        self.version = version
        self.source_id = source_id
        self.queries = []

    def query_experience(self, text, top_k, threshold, venue_id, strict=False):
        self.queries.append(
            {
                "text": text,
                "top_k": top_k,
                "threshold": threshold,
                "venue_id": venue_id,
                "strict": strict,
            }
        )
        return [
            {
                "id": "sop:west-lake-park:2101",
                "content": "向量索引中的候选正文",
                "score": 0.93,
                "metadata": {
                    "source_id": self.source_id,
                    "source_type": "SOP",
                    "title": "向量索引中的候选标题",
                    "version": self.version,
                    "status": "PUBLISHED",
                    "venue_id": venue_id,
                },
            }
        ]


class SnapshotWriteFailureDatabase:
    def __init__(self, database):
        self.database = database

    async def fetch_one(self, sql, parameters=()):
        return await self.database.fetch_one(sql, parameters)

    async def fetch_all(self, sql, parameters=()):
        return await self.database.fetch_all(sql, parameters)

    async def execute(self, sql, parameters=()):
        if "INSERT INTO knowledge_retrieval_snapshots" in sql:
            raise RuntimeError("simulated retrieval evidence outage")
        return await self.database.execute(sql, parameters)


class ExplodingVectorStore:
    backend_mode = "test"

    def query_experience(self, text, top_k, threshold, venue_id, strict=False):
        raise RuntimeError("authorization failed for sk-super-secret-token-123456")


class SopAndLiveCaseVectorStore(SopVectorStore):
    def query_experience(self, text, top_k, threshold, venue_id, strict=False):
        self.queries.append(
            {
                "text": text,
                "top_k": top_k,
                "threshold": threshold,
                "venue_id": venue_id,
                "strict": strict,
            }
        )
        return [
            {
                "id": "evt_closed_case",
                "content": "事件创建时的旧向量正文",
                "score": 0.99,
                "metadata": {
                    "source_id": "closed-case-1",
                    "source_type": "LIVE",
                    "status": "OPEN",
                    "version": 1,
                    "venue_id": venue_id,
                },
            },
            {
                "id": "sop:west-lake-park:2101",
                "content": "向量索引中的候选正文",
                "score": 0.81,
                "metadata": {
                    "source_id": "2101",
                    "source_type": "SOP",
                    "title": "向量索引中的候选标题",
                    "version": "2.1",
                    "status": "PUBLISHED",
                    "venue_id": venue_id,
                },
            },
        ]


class ExperienceVectorStore:
    backend_mode = "test"

    def query_experience(self, text, top_k, threshold, venue_id, strict=False):
        return [
            {
                "id": "experience:west-lake-park:experience-card-1:v1",
                "content": "雨后异响应保持停运并检查护板间隙。",
                "score": 0.88,
                "metadata": {
                    "card_id": "experience-card-1",
                    "business_id": "JY-0001",
                    "asset_type": "EXPERIENCE_CARD",
                    "status": "PUBLISHED",
                    "version": 1,
                    "venue_id": venue_id,
                },
            }
        ]


async def seeded_database(tmp_path, *, include_knowledge=True):
    database = AsyncDBClient(tmp_path / "evidence-retrieval.db")
    await init_database(database)
    now = 1785283200.0
    await database.execute(
        "INSERT INTO venues (id, name, status, created_at, updated_at) VALUES (?, ?, 'ACTIVE', ?, ?)",
        ("west-lake-park", "西湖园区", now, now),
    )
    await database.execute(
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
            now,
            now,
        ),
    )
    await database.execute(
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
            "保持车辆停运并隔离，完成轮端检查前禁止载客。",
            1,
            "2.1",
            "knowledge-owner",
            "knowledge-owner",
            now,
            now,
            now,
        ),
    )
    if include_knowledge:
        await database.execute(
            """
            INSERT INTO knowledge_documents (
                id, venue_id, title, content, category, source_type, source_id,
                version, status, tags_json, vector_doc_id, created_by, updated_by,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'SOP', ?, 1, 'ACTIVE', '[]', ?, ?, ?, ?, ?)
            """,
            (
                "sop-2101",
                "west-lake-park",
                "观光车雨后复运与异常异响处置",
                "保持车辆停运并隔离，完成轮端检查前禁止载客。",
                "设备安全",
                "2101",
                "sop:west-lake-park:2101",
                "knowledge-owner",
                "knowledge-owner",
                now,
                now,
            ),
        )
    return database


def retrieval_request(trace_id):
    return RetrievalRequest(
        query="观光车雨后出现异响，如何安全处置",
        venue_id="west-lake-park",
        trace_id=trace_id,
        user_id="knowledge-owner",
        message_id=f"message-{trace_id}",
        session_id="session-evidence",
    )


@pytest.mark.asyncio
async def test_version_drift_is_recorded_and_never_returned_as_a_reference(tmp_path):
    database = await seeded_database(tmp_path)
    vector_store = SopVectorStore(version="2.0")
    retriever = EvidenceBackedKnowledgeRetriever(
        database=database,
        vector_store=vector_store,
    )

    try:
        result = await retriever.retrieve(retrieval_request("trace-version-drift"))

        assert result.status == "ZERO_HITS"
        assert result.references == ()
        snapshot = await database.fetch_one(
            "SELECT * FROM knowledge_retrieval_snapshots WHERE id = ?",
            (result.snapshot_id,),
        )
        attempts = json.loads(snapshot["attempts_json"])
        assert [attempt["strategy"] for attempt in attempts] == ["semantic", "broad"]
        assert {
            hit["rejection_reason"]
            for attempt in attempts
            for hit in attempt["hits"]
        } == {"VERSION_MISMATCH"}
        assert json.loads(snapshot["references_json"]) == []
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_missing_relational_source_is_recorded_and_never_returned(tmp_path):
    database = await seeded_database(tmp_path, include_knowledge=False)
    retriever = EvidenceBackedKnowledgeRetriever(
        database=database,
        vector_store=SopVectorStore(),
    )

    try:
        result = await retriever.retrieve(retrieval_request("trace-source-missing"))

        assert result.status == "ZERO_HITS"
        assert result.references == ()
        snapshot = await database.fetch_one(
            "SELECT * FROM knowledge_retrieval_snapshots WHERE id = ?",
            (result.snapshot_id,),
        )
        attempts = json.loads(snapshot["attempts_json"])
        assert {
            hit["rejection_reason"]
            for attempt in attempts
            for hit in attempt["hits"]
        } == {"SOURCE_NOT_FOUND_OR_INACTIVE"}
        assert snapshot["selected_count"] == 0
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_snapshot_write_failure_prevents_valid_reference_from_returning(tmp_path):
    database = await seeded_database(tmp_path)
    failing_database = SnapshotWriteFailureDatabase(database)
    retriever = EvidenceBackedKnowledgeRetriever(
        database=failing_database,
        vector_store=SopVectorStore(),
    )

    try:
        with pytest.raises(
            KnowledgeSnapshotPersistenceError,
            match="拒绝返回引用",
        ):
            await retriever.retrieve(retrieval_request("trace-snapshot-write-failure"))

        snapshots = await database.fetch_all(
            "SELECT * FROM knowledge_retrieval_snapshots WHERE trace_id = ?",
            ("trace-snapshot-write-failure",),
        )
        assert snapshots == []
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_trace_timeline_separates_business_and_technical_retrieval_evidence(tmp_path):
    database = await seeded_database(tmp_path)
    retriever = EvidenceBackedKnowledgeRetriever(
        database=database,
        vector_store=SopVectorStore(),
    )

    try:
        result = await retriever.retrieve(retrieval_request("trace-visible-evidence"))

        manager_view = await build_trace_timeline(
            database,
            venue_id="west-lake-park",
            trace_id="trace-visible-evidence",
            technical=False,
        )
        assert manager_view["summary"]["knowledge_retrievals"] == 1
        assert manager_view["summary"]["knowledge_hits"] == 1
        assert manager_view["retrievals"][0]["id"] == result.snapshot_id
        assert "attempts" not in manager_view["retrievals"][0]
        assert "query_sha256" not in manager_view["retrievals"][0]
        assert "vector_doc_id" not in manager_view["retrievals"][0]["references"][0]
        assert {
            item["resource_id"]
            for item in manager_view["timeline"]
            if item["kind"] == "KNOWLEDGE_RETRIEVAL"
        } == {result.snapshot_id}

        admin_view = await build_trace_timeline(
            database,
            venue_id="west-lake-park",
            trace_id="trace-visible-evidence",
            technical=True,
        )
        assert len(admin_view["retrievals"][0]["query_sha256"]) == 64
        assert admin_view["retrievals"][0]["attempts"][0]["strategy"] == "semantic"
        assert (
            admin_view["retrievals"][0]["references"][0]["vector_doc_id"]
            == "sop:west-lake-park:2101"
        )
        assert await build_trace_timeline(
            database,
            venue_id="east-lake-park",
            trace_id="trace-visible-evidence",
            technical=True,
        ) is None
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_trace_timeline_marks_experience_evidence_collection_failure_degraded(
    tmp_path,
    monkeypatch,
):
    database = await seeded_database(tmp_path)
    now = 1785283200.0
    try:
        await database.execute(
            """
            INSERT INTO message_runs (
                message_id, trace_id, session_id, user_id, venue_id, content,
                status, created_at, updated_at, processed_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'COMPLETED', ?, ?, ?)
            """,
            (
                "message-degraded-experience-evidence",
                "trace-degraded-experience-evidence",
                "session-degraded-experience-evidence",
                "knowledge-owner",
                "west-lake-park",
                "检查追踪证据是否完整",
                now,
                now,
                now,
            ),
        )
        original_fetch_all = database.fetch_all

        async def fail_experience_usage_query(sql, parameters=()):
            if "FROM experience_usage_logs usage" in sql:
                raise RuntimeError("private database detail")
            return await original_fetch_all(sql, parameters)

        monkeypatch.setattr(database, "fetch_all", fail_experience_usage_query)

        timeline = await build_trace_timeline(
            database,
            venue_id="west-lake-park",
            trace_id="trace-degraded-experience-evidence",
            technical=True,
        )

        assert timeline["status"] == "DEGRADED"
        assert timeline["experience_usages"] == []
        evidence_items = [
            item
            for item in timeline["timeline"]
            if item["kind"] == "EVIDENCE_COLLECTION"
        ]
        assert len(evidence_items) == 1
        assert evidence_items[0]["status"] == "DEGRADED"
        assert "private database detail" not in str(timeline)
    finally:
        await database.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("message_status", ["QUEUED", "RECOVERING", "RETRYING"])
async def test_trace_timeline_keeps_active_message_states_running(tmp_path, message_status):
    database = await seeded_database(tmp_path)
    now = 1785283200.0
    trace_id = f"trace-active-{message_status.lower()}"
    try:
        await database.execute(
            """
            INSERT INTO message_runs (
                message_id, trace_id, session_id, user_id, venue_id, content,
                status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"message-active-{message_status.lower()}",
                trace_id,
                "session-active-trace",
                "knowledge-owner",
                "west-lake-park",
                "检查仍在处理中的消息",
                message_status,
                now,
                now,
            ),
        )

        timeline = await build_trace_timeline(
            database,
            venue_id="west-lake-park",
            trace_id=trace_id,
            technical=True,
        )

        assert timeline["status"] == "RUNNING"
    finally:
        await database.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("message_status", ["RETRY_REQUIRED", "DEAD_LETTERED"])
async def test_trace_timeline_marks_terminal_message_recovery_states_failed(
    tmp_path,
    message_status,
):
    database = await seeded_database(tmp_path)
    now = 1785283200.0
    trace_id = f"trace-failed-{message_status.lower()}"
    try:
        await database.execute(
            """
            INSERT INTO message_runs (
                message_id, trace_id, session_id, user_id, venue_id, content,
                status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"message-failed-{message_status.lower()}",
                trace_id,
                "session-failed-trace",
                "knowledge-owner",
                "west-lake-park",
                "检查需要人工恢复的消息",
                message_status,
                now,
                now,
            ),
        )

        timeline = await build_trace_timeline(
            database,
            venue_id="west-lake-park",
            trace_id=trace_id,
            technical=True,
        )

        assert timeline["status"] == "FAILED"
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_failed_retrieval_snapshot_redacts_secrets_and_has_no_references(tmp_path):
    database = await seeded_database(tmp_path)
    retriever = EvidenceBackedKnowledgeRetriever(
        database=database,
        vector_store=ExplodingVectorStore(),
    )

    try:
        with pytest.raises(KnowledgeRetrievalError) as error:
            await retriever.retrieve(retrieval_request("trace-redacted-failure"))

        assert "super-secret" not in str(error.value)
        formatted_error = "".join(
            traceback.format_exception(error.type, error.value, error.tb)
        )
        assert "super-secret" not in formatted_error
        snapshot = await database.fetch_one(
            "SELECT * FROM knowledge_retrieval_snapshots WHERE trace_id = ?",
            ("trace-redacted-failure",),
        )
        assert snapshot["status"] == "FAILED"
        assert snapshot["selected_count"] == 0
        assert json.loads(snapshot["references_json"]) == []
        assert "super-secret" not in snapshot["error_message"]
        assert "[REDACTED]" in snapshot["error_message"]
        attempts = json.loads(snapshot["attempts_json"])
        assert attempts[0]["status"] == "FAILED"
        assert "super-secret" not in attempts[0]["error_message"]
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_closed_live_event_is_reusable_but_published_sop_keeps_priority(tmp_path):
    database = await seeded_database(tmp_path)
    now = 1785286800.0
    await database.execute(
        """
        INSERT INTO confirmed_events (
            event_id, business_id, push_id, from_user, raw_text, event_type,
            severity, context_trigger_data, memory_content, vector_doc_id,
            created_at, confirmed_at, venue_id, source_type, status, assigned_to,
            resolution, trace_id, closed_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, '{}', ?, ?, ?, ?, ?, 'LIVE', 'CLOSED', ?, ?, ?, ?, ?)
        """,
        (
            "closed-case-1",
            "SJ-CLOSED-0001",
            "message-original",
            "operator-original",
            "雨后观光车出现轮端异响",
            "设备异响",
            "P1",
            "雨后观光车出现轮端异响",
            "evt_closed_case",
            now - 3600,
            now - 3500,
            "west-lake-park",
            "maintenance-owner",
            "保持停运，调整护板间隙后复检通过。",
            "trace-original",
            now,
            now,
        ),
    )
    vector_store = SopAndLiveCaseVectorStore()
    retriever = EvidenceBackedKnowledgeRetriever(
        database=database,
        vector_store=vector_store,
    )
    request = RetrievalRequest(
        query="雨后观光车异响能否载客",
        venue_id="west-lake-park",
        trace_id="trace-source-priority",
        user_id="knowledge-owner",
        top_k=1,
    )

    try:
        result = await retriever.retrieve(request)

        assert result.status == "SUCCEEDED"
        assert result.references[0]["source_type"] == "SOP"
        assert vector_store.queries[0]["top_k"] == 8
        snapshot = await database.fetch_one(
            "SELECT attempts_json FROM knowledge_retrieval_snapshots WHERE id = ?",
            (result.snapshot_id,),
        )
        hits = json.loads(snapshot["attempts_json"])[0]["hits"]
        assert next(hit for hit in hits if hit["source_type"] == "LIVE")["rejection_reason"] == "TOP_K_LIMIT"
        assert next(hit for hit in hits if hit["source_type"] == "SOP")["selected"] is True
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_published_experience_requires_explicit_server_side_authorization(tmp_path):
    database = await seeded_database(tmp_path)
    await init_experience_schema(database)
    now = 1785290400.0
    await database.execute(
        """
        INSERT INTO expert_profiles (
            id, business_id, venue_id, user_id, display_name, years_experience,
            expertise_json, authorization_status, status, created_by,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 12, '[]', 'APPROVED', 'ACTIVE', ?, ?, ?)
        """,
        (
            "expert-1",
            "ZJ-0001",
            "west-lake-park",
            "expert-user-1",
            "张建国",
            "knowledge-owner",
            now,
            now,
        ),
    )
    await database.execute(
        """
        INSERT INTO experience_cards (
            id, business_id, venue_id, expert_id, title, applicable_context,
            signals_json, decision_rule, recommended_actions_json, rationale,
            prohibitions_json, exceptions_json, source_excerpts_json, status,
            current_version, published_version, vector_doc_id, index_status,
            created_by, published_by, published_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PUBLISHED', 1, 1, ?, 'INDEXED', ?, ?, ?, ?, ?)
        """,
        (
            "experience-card-1",
            "JY-0001",
            "west-lake-park",
            "expert-1",
            "雨后观光车轮端间歇性金属异响判断",
            "雨后晨检发现随车速变化的金属擦声",
            '["异响随车速变化"]',
            "未完成护板间隙检查前不得载客",
            '["停运隔离", "检查护板间隙"]',
            "雨后护板可能轻微变形并与轮端干涉",
            '["不得带客试车"]',
            '["出现发热或焦味时立即升级"]',
            '["昨天淋雨后出现间歇性擦声"]',
            "experience:west-lake-park:experience-card-1:v1",
            "knowledge-owner",
            "knowledge-owner",
            now,
            now,
            now,
        ),
    )
    retriever = EvidenceBackedKnowledgeRetriever(
        database=database,
        vector_store=ExperienceVectorStore(),
    )

    try:
        denied = await retriever.retrieve(retrieval_request("trace-experience-denied"))
        assert denied.status == "ZERO_HITS"
        denied_snapshot = await database.fetch_one(
            "SELECT attempts_json FROM knowledge_retrieval_snapshots WHERE id = ?",
            (denied.snapshot_id,),
        )
        assert {
            hit["rejection_reason"]
            for attempt in json.loads(denied_snapshot["attempts_json"])
            for hit in attempt["hits"]
        } == {"NOT_AUTHORIZED"}

        await database.execute(
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
        allowed = await retriever.retrieve(retrieval_request("trace-experience-allowed"))
        assert allowed.status == "SUCCEEDED"
        assert allowed.references[0]["source_id"] == "experience-card-1"
        assert allowed.references[0]["expert_name"] == "张建国"
    finally:
        await database.close()
