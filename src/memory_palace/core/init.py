"""
核心引擎层 (Core Engine Layer)

本包为 Memory Palace OS 提供底层的运行时基础设施，涵盖：
1. 企微 Webhook 鉴权与高并发网关 (Gateway)
2. 智能体基础契约与流转结构 (Skill Base & DTO)
3. 状态机驱动的管弦编排中枢 (Orchestrator)
4. 多模态会话的上下文管控 (Context)

【架构纪律】
外部业务层 (如 skills/) 严禁越权调用本包内部的私有调度类。
必须统一通过此 __init__.py 文件暴露的 __all__ 白名单进行导入。
"""

import logging

# 注册子模块日志防污染兜底
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

# =============================================================================
# 核心 API 暴露白名单 (Public API Surface)
# 作用: 收敛底层复杂度。智能体开发者只需要知道 BaseAgentSkill 和 SkillOutput
#       这两个类即可开发新的特种智能体，无需关心网关是如何解析 XML 或调度协程的。
# =============================================================================

try:
    from .skill_base import BaseAgentSkill, SkillOutput

    __all__ = [
        "BaseAgentSkill",
        "SkillOutput",
    ]

except ImportError as e:
    logger.debug(f"Core 引擎层底座尚未完全挂载。延迟错误信息: {e}")
    __all__ = []