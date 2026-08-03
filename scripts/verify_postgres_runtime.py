"""Verify PostgreSQL persistence and restart recovery for core MVP state."""

from __future__ import annotations

import asyncio
import os
import time
import uuid

from src.memory_palace.core.permissions import PermissionEngine
from src.memory_palace.core.task_graph import TaskGraph
from src.memory_palace.knowledge.db_init import init_database
from src.memory_palace.knowledge.postgres_client import PostgresDBClient
from src.memory_palace.skills.persona_extract.skill import PersonaExtractSkill


async def main() -> None:
    db = PostgresDBClient()
    venue_id = os.environ.get("DEFAULT_VENUE_ID", "venue-hq")
    session_id = f"verify-{uuid.uuid4().hex}"
    task_id = None
    approval_id = None
    interview_id = None

    async def skip_external_notification(_approval) -> None:
        return None

    try:
        await init_database(db)
        llm_log_columns = await db.fetch_one(
            """
            SELECT COUNT(*) AS count
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'llm_call_logs'
            """
        )
        if not llm_log_columns or int(llm_log_columns["count"]) < 16:
            raise RuntimeError("LLM call evidence schema verification failed")
        now = time.time()
        await db.execute(
            """
            INSERT INTO sessions (
                session_id, user_id, venue_id, agent_name, stage,
                message_count, created_at, updated_at
            ) VALUES (?, 'runtime-verifier', ?, 'router', 'active', 0, ?, ?)
            """,
            (session_id, venue_id, now, now),
        )

        graph = TaskGraph(db)
        task = await graph.create_task(
            session_id=session_id,
            description="验证任务状态可在进程重建后恢复",
            venue_id=venue_id,
        )
        task_id = task.id

        recovered_graph = TaskGraph(db)
        await recovered_graph.reload_from_db()
        recovered_task = await recovered_graph.get_task(task.id)
        if recovered_task is None or recovered_task.venue_id != venue_id:
            raise RuntimeError("TaskGraph recovery verification failed")

        engine = PermissionEngine(db)
        engine._notify_admin = skip_external_notification
        request = await engine.check_and_execute(
            "send_sms",
            {"message": "runtime verification only"},
            {
                "session_id": session_id,
                "user_id": "runtime-verifier",
                "agent_name": "runtime-verifier",
                "venue_id": venue_id,
            },
        )
        approval_id = request.get("approval_id")
        if not approval_id:
            raise RuntimeError("Approval persistence verification failed")

        recovered_engine = PermissionEngine(db)
        await recovered_engine.reload_from_db()
        recovered_approval = await recovered_engine.get_approval(
            approval_id,
            venue_id=venue_id,
        )
        if recovered_approval is None:
            raise RuntimeError("Approval recovery verification failed")

        interview = await PersonaExtractSkill(db_client=db).start_interview(
            job_title="运行恢复验证岗",
            venue_id=venue_id,
            trace_id=session_id,
        )
        interview_id = interview.structured_data.get("interview_id")
        recovered_interview = await PersonaExtractSkill(db_client=db)._load_interview_state(
            interview_id,
            venue_id,
        )
        if recovered_interview is None or recovered_interview["current_question"] != 1:
            raise RuntimeError("Persona interview recovery verification failed")

        print("PostgreSQL runtime recovery verified: schema, task, approval, persona interview, tenant scope")
    finally:
        if interview_id:
            await db.execute("DELETE FROM persona_interviews WHERE id = ?", (interview_id,))
        if approval_id:
            await db.execute("DELETE FROM approval_requests WHERE approval_id = ?", (approval_id,))
        if task_id:
            await db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        await db.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
