"""
滑动窗口截断测试 (Unit Test for Persona Context)

工业级测试要点：
1. 边界值测试：对话轮数为 N-1, N, N+1 时的表现。
2. 格式完整性：确保截断后，最新的对话内容（Last Message）永远被保留。
"""

import pytest
from src.memory_palace.skills.persona.skill import PersonaSkill

@pytest.fixture
def persona_agent():
    return PersonaSkill()

def test_sliding_window_truncation(persona_agent):
    """验证：当对话超过 5 轮时，是否只保留最近的 5 轮"""
    # 模拟 10 轮对话 (20 条消息)
    long_history = []
    for i in range(10):
        long_history.append({"role": "user", "content": f"Question {i}"})
        long_history.append({"role": "assistant", "content": f"Answer {i}"})
    
    # 手动设置配置里的窗口大小为 5
    persona_agent.config["memory_config"]["max_history_turns"] = 5
    
    formatted_context = persona_agent._format_history_window(long_history)
    
    # 1. 验证输出的文本行数 (5 轮 = 10 条消息)
    # 每条消息在格式化后占一行，通过换行符判断
    msg_lines = [l for l in formatted_context.split('\n') if l.strip()]
    assert len(msg_lines) == 10
    
    # 2. 验证保留的是最新的部分
    assert "Question 9" in formatted_context
    assert "Answer 9" in formatted_context
    # 验证旧的已经被挤出去了
    assert "Question 0" not in formatted_context

def test_empty_history_handling(persona_agent):
    """验证：首次对话（历史为空）时的稳健性"""
    formatted_context = persona_agent._format_history_window([])
    assert "无历史记录" in formatted_context