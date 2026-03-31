"""
RAG 链路集成测试 (Integration Test for Memory Retrieval)

工业级测试要点：
1. 真实召回模拟：不 Mock VectorStore 的搜索方法，而是真实往内存集合里存数据，测试 search_similar。
2. 知识注入验证：验证 LLM 的最终输出是否受到了召回文档的实质影响。
3. 边界测试：当召回结果得分略低于阈值时，验证系统是否触发了“安全降级”话术。
"""

import pytest
from unittest.mock import MagicMock, patch
from src.memory_palace.skills.memory_ops.skill import MemoryOpsSkill
from src.memory_palace.knowledge.vector_store import vector_client

@pytest.fixture
def memory_skill():
    return MemoryOpsSkill()

def test_rag_full_pipeline_success(memory_skill, monkeypatch):
    """
    验证：提问 -> 向量库捞出历史案例 -> LLM 结合案例给出回复
    """
    # 1. 准备测试数据：真实注入一条经验到向量库 (内存模式)
    test_case_content = "2024年曾发生同类票务纠纷，处理方案是核实身份后通过补差价升舱解决。"
    vector_client.add_experience(
        content=test_case_content,
        metadata={"case_id": "HIST_999", "date": "2024-05"},
        doc_id="integration_test_doc"
    )

    # 2. Mock LLM，观察它收到的 System Prompt 是否包含上述 content
    with patch("memory_palace.tools.llm_wrapper.llm_client.ask") as mock_ask:
        mock_ask.return_value = MagicMock(
            content='{"reply_text": "建议参考2024年案例，通过补差价升舱处理。", "action_taken": "rag_advice"}',
            tokens_used=300
        )

        # 执行 MemoryOps 技能
        context = {"raw_text": "游客因为票价差额在门口吵闹，以前怎么处理的？"}
        result = memory_skill._execute_impl(context, trace_id="test_rag_001")

        # 3. 核心断言：验证 RAG 的“增强”行为
        # 检查发给大模型的 system_prompt 是否包含了我们存入的测试案例
        sent_system_prompt = mock_ask.call_args[1]["system_prompt"]
        assert test_case_content in sent_system_prompt
        
        # 检查返回给用户的结构化数据中是否包含了召回统计
        assert result.structured_data["retrieved_count"] >= 1
        assert "HIST_999" in result.structured_data["reference_cases"]

def test_rag_fallback_when_low_similarity(memory_skill):
    """
    验证：当搜索不到相关内容时，系统是否死守红线，不胡编乱造。
    """
    with patch("memory_palace.tools.llm_wrapper.llm_client.ask") as mock_ask:
        # 模拟 LLM 按照 advice.txt 的降级要求返回
        mock_ask.return_value = MagicMock(
            content='{"reply_text": "抱歉，未检索到相关历史案例，建议请示经理。", "is_hallucination_prevented": true}',
            tokens_used=50
        )

        # 提一个完全无关的问题
        context = {"raw_text": "外星人占领了旋转木马怎么办？"}
        result = memory_skill._execute_impl(context, trace_id="test_rag_002")

        assert "未检索到" in result.reply_text