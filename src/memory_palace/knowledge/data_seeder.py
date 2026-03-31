"""
种子数据注入器 (Knowledge Seeder)

功能：
1. 强行同步 SOP 数据库。
2. 预热向量库，灌入历史典型的处突经验案例。
"""

import uuid
import asyncio
from loguru import logger
from src.memory_palace.tools.db_client import db_manager, SOPDocument
from src.memory_palace.knowledge.vector_store import vector_client


def seed_knowledge_base():
    """同步入口（供命令行直接运行）"""
    asyncio.run(_seed_knowledge_base_async())


async def _seed_knowledge_base_async():
    """异步种子数据注入"""
    logger.info("开始执行种子数据灌溉...")

    # 1. 注入 SOP 结构化法典 (SQL via SQLAlchemy session)
    with db_manager.session_scope() as session:
        # 清理旧规则，保持版本唯一
        session.query(SOPDocument).delete()

        initial_sops = [
            SOPDocument(category="安全", title="游客心脏骤停应急预案",
                        content="1.立即拨打120; 2.取用 AED 到场; 3.疏散围观人群; 4.配合救护车进场。"),
            SOPDocument(category="票务", title="恶意退票纠纷",
                        content="1.核实入园状态; 2.调取闸机录像; 3.告知法律风险; 4.协商转赠或改期。"),
        ]
        session.add_all(initial_sops)
        logger.success("SOP 核心法典注入成功。")

    # 2. 注入历史经验片段 (Vector)
    historical_cases = [
        {
            "content": "2024年国庆期间，过山车发生安全锁虚接误报。处理经验：先断电锁死，手动复位，而不是直接通过系统重启。",
            "meta": {"type": "设施维护", "severity": "P0", "date": "20241001"}
        },
        {
            "content": "曾在酒吧区发生由于音量过大导致的集体客诉。处理经验：AI 指挥官下调音量 20%，并赠送全场代币，平息了情绪。",
            "meta": {"type": "投诉处理", "severity": "P2", "date": "20250115"}
        }
    ]

    for case in historical_cases:
        vector_client.upsert_experience(
            content=case["content"],
            metadata=case["meta"],
            doc_id=f"SEED_{uuid.uuid4().hex[:8]}"
        )

    logger.success("历史向量经验预热完成。系统已具备初步'智力'。")


if __name__ == "__main__":
    seed_knowledge_base()
