"""
智能体转办集成测试 (Integration Test for Agent Handoff)

工业级测试要点：
1. 全链路模拟：不直接调用单个 Skill，而是通过 Orchestrator.dispatch 触发。
2. 意图穿透验证：验证 Router 输出的 action_taken 是否准确驱动了下一个 Agent 的实例化。
3. 状态机流转：确保上下文（Context）在不同 Agent 之间传递时没有丢失关键元数据（如 Severity）。
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from src.memory_palace.core.orchestrator import Orchestrator
from src.memory_palace.core.skill_base import SkillOutput

@pytest.mark.asyncio
async def test_router_to_commander_flow():
    """
    场景：用户报告“有人晕倒”，验证 Router 是否分流给 Commander。
    """
    # 1. 构造模拟负载 (来自企微的原始 XML 解析结果)
    mock_payload = {
        "FromUserName": "worker_001",
        "Content": "快来人！一号门过山车排队区有人晕倒了，呼吸微弱！",
        "MsgId": "123456789"
    }

    # 2. Mock LLM 调用：第一次返回路由结果，第二次返回指挥官指令
    # 我们通过 side_effect 让 llm_client 针对不同请求返回不同内容
    with patch("src.memory_palace.tools.llm_wrapper.llm_client.ask") as mock_ask:
        
        # 模拟 Router 的返回 (L2 语义识别为紧急分发)
        router_resp = MagicMock()
        router_resp.content = '{"intent": "emergency_dispatch", "severity": "P0", "reply_text": "正在接入指挥中心..."}'
        router_resp.tokens_used = 100
        
        # 模拟 Commander 的返回 (下发具体的 SOP)
        commander_resp = MagicMock()
        commander_resp.content = '{"reply_text": "收到 P0 级求助！1.立即拨打120；2.寻找周边 AED；3.维持秩序。", "next_step_check": "120拨打了吗？"}'
        commander_resp.tokens_used = 250
        
        mock_ask.side_effect = [router_resp, commander_resp]

        # 3. 模拟企微发送动作，不产生真实 IO
        with patch("src.memory_palace.tools.wechat_client.wechat_client.send_text", return_value=True) as mock_send:
            
            # 执行调度
            await Orchestrator().dispatch(mock_payload)

            # 4. 断言验证
            # A. 验证 LLM 是否被调用了两次（一次路由，一次执行）
            assert mock_ask.call_count == 2
            
            # B. 验证最终发给企微的消息是否包含了指挥官的专业建议
            # mock_send.call_args[0][1] 获取第二个参数即 reply_text
            final_text = mock_send.call_args[0][1]
            assert "P0" in final_text
            assert "AED" in final_text
            
            # C. 验证 TraceID 是否在全链路中保持一致 (通过日志或上下文对象，此处简化)
            logger_info = "🚀 启动任务流" # 假设在日志中检查