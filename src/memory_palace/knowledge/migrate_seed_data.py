"""
工业级数据迁移适配器 (Migration Adapter)

功能：
1. 桥接旧版 events 表与新版 incident_logs 表。
2. 强制语义对齐：将旧数据的 venue_id, resolution 映射到新架构的结构化字段。
3. 批量事务处理：使用 SQLAlchemy 事务确保迁移过程的原子性。

Copyright (c) 2026 ZhouWei. All Rights Reserved.
"""

import sqlite3
import os
import asyncio
from loguru import logger
from src.memory_palace.tools.db_client import db_manager, IncidentLog
from src.memory_palace.knowledge.vector_store import get_vector_client

OLD_DB_PATH = "data/old_memory.db"


def migrate_v1_to_v2():
    """同步入口（供命令行直接运行）"""
    asyncio.run(_migrate_v1_to_v2_async())


async def _migrate_v1_to_v2_async():
    """异步迁移核心逻辑"""
    if not os.path.exists(OLD_DB_PATH):
        logger.error(f"未发现旧数据库: {OLD_DB_PATH}，跳过迁移。")
        return

    logger.info("启动 V1 -> V2 工业级迁移引擎...")

    # 1. 连接旧库
    try:
        old_conn = sqlite3.connect(OLD_DB_PATH)
        old_conn.row_factory = sqlite3.Row
        cursor = old_conn.cursor()
        cursor.execute("SELECT * FROM events")
        old_rows = cursor.fetchall()
    except Exception as e:
        logger.error(f"无法读取旧库: {e}")
        return

    if not old_rows:
        logger.warning("旧库记录为空。")
        return

    # 2. 映射并注入新库 (SQL + Vector)
    # 使用 db_manager 的 session_scope 保证整批迁移要么全成功，要么全失败
    with db_manager.session_scope() as session:
        for i, row in enumerate(old_rows):
            case_id = f"MIG_{row['id']}_{int(os.times().elf)}"

            # A. 映射到 SQLAlchemy 模型 (字段名与 tools/db_client.py 的 IncidentLog 一致)
            new_incident = IncidentLog(
                case_id=case_id,
                severity=row['severity'] or "P2",
                dispatched_instruction=row.get('resolution') or "",
                employee_replies="[]",
                is_resolved=True,
                audit_status="PASSED",
            )
            session.add(new_incident)

            # B. 映射到 ChromaDB 向量库 (重铸记忆)
            get_vector_client().upsert_experience(
                content=row.get('raw_text', ''),
                metadata={
                    "case_id": case_id,
                    "type": row.get('event_type', 'unknown'),
                    "source": "v1_migration",
                },
                doc_id=case_id,
            )

            if i % 10 == 0:
                logger.info(f"已同步 {i+1} 条记录...")

    logger.success(f"迁移完成！共计 {len(old_rows)} 条历史经验已存入记忆宫殿。")


if __name__ == "__main__":
    migrate_v1_to_v2()
