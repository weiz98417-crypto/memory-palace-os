"""
智能体业务技能包 (Business Agent Skills) - 统一入口
================================================================
职责：
  1. 提供 @register_skill 装饰器，自动注册所有 Agent 类
  2. 维护全局技能注册表 (Skill Registry)
  3. 支持动态加载/卸载技能（热更新基础）
  4. 提供统一的技能查询接口

设计原则：
  - 所有 Skill 类在 import 时自动注册（模块级副作用）
  - 外部只允许通过 get_skill_by_name() 获取技能，不直接实例化
  - 调度层（Orchestrator）只依赖本模块，不感知具体 Skill 实现

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

from typing import Dict, List, Optional, Type, Any

# 使用相对导入，与 skills 子包中的相对导入保持一致
from ..core.skill_base import BaseAgentSkill

# ==============================================================================
# 全局技能注册表
# ==============================================================================

# 存储类引用（而非实例），由 @register_skill 装饰器填充
_SKILL_REGISTRY: Dict[str, Type[BaseAgentSkill]] = {}
_SKILL_NAMES: List[str] = []


# ==============================================================================
# 注册装饰器
# ==============================================================================

def register_skill(name: str):
    """
    技能注册装饰器。

    用法：
        @register_skill("router")
        class RouterSkill(BaseAgentSkill):
            ...

    效果：
        - 将类引用注册到全局 _SKILL_REGISTRY（延迟实例化）
        - 导入 skills 模块时自动执行（模块级副作用）
        - 后续通过 get_skill_by_name("router") 获取实例
    """
    def decorator(cls: Type[BaseAgentSkill]):
        if name in _SKILL_REGISTRY:
            # 防止重复注册
            import warnings
            warnings.warn(f"技能 '{name}' 已注册，将被覆盖。")
        _SKILL_REGISTRY[name] = cls
        if name not in _SKILL_NAMES:
            _SKILL_NAMES.append(name)
        from loguru import logger
        logger.debug(f"[SkillRegistry] 技能已注册: {name} ({cls.__name__})")
        return cls
    return decorator


# ==============================================================================
# 查询接口
# ==============================================================================

def get_skill_by_name(name: str) -> Optional[BaseAgentSkill]:
    """
    智能体工厂方法：根据名称获取已实例化的智能体对象。

    :param name: 技能名称（如 "router", "commander", "watcher"）
    :return: BaseAgentSkill 实例，不存在则返回 None
    """
    skill_cls = _SKILL_REGISTRY.get(name)
    if not skill_cls:
        return None
    # 延迟实例化：每次调用返回一个新实例
    try:
        return skill_cls()
    except Exception as e:
        from loguru import logger
        logger.error(f"技能 '{name}' 实例化失败: {e}")
        return None


def get_registered_skills() -> List[Type[BaseAgentSkill]]:
    """获取所有已注册的技能类（未实例化）"""
    return list(_SKILL_REGISTRY.values())


def list_skill_names() -> List[str]:
    """列出所有已注册技能的名称"""
    return _SKILL_NAMES.copy()


def is_skill_enabled(name: str) -> bool:
    """检查技能是否启用"""
    skill = _SKILL_REGISTRY.get(name)
    if skill is None:
        return False
    return getattr(skill, "enabled", True)


def enable_skill(name: str) -> bool:
    """启用指定技能"""
    skill = _SKILL_REGISTRY.get(name)
    if skill is None:
        return False
    skill.enabled = True
    return True


def disable_skill(name: str) -> bool:
    """禁用指定技能（不注销，仍在注册表中）"""
    skill = _SKILL_REGISTRY.get(name)
    if skill is None:
        return False
    skill.enabled = False
    return True


def reload_skill(name: str) -> bool:
    """
    重新加载指定技能的配置（热更新入口）。
    触发 invalidate_prompt_cache() 清除缓存。
    """
    skill_cls = _SKILL_REGISTRY.get(name)
    if skill_cls is None:
        from loguru import logger
        logger.warning(f"[SkillRegistry] reload_skill: 技能 '{name}' 未注册，无法重载。")
        return False
    # 重新实例化以触发配置重载
    try:
        instance = skill_cls()
        if hasattr(instance, "invalidate_prompt_cache"):
            instance.invalidate_prompt_cache()
        from loguru import logger
        logger.info(f"[SkillRegistry] 技能 '{name}' 配置已热更新。")
        return True
    except Exception as e:
        from loguru import logger
        logger.error(f"[SkillRegistry] reload_skill: 技能 '{name}' 重载失败: {e}")
        return False


def reload_all_skills() -> Dict[str, bool]:
    """重新加载所有技能"""
    return {name: reload_skill(name) for name in _SKILL_NAMES}


def get_skill_info(name: str) -> Optional[Dict[str, Any]]:
    """获取技能的元信息（基于类定义，不实例化）"""
    skill_cls = _SKILL_REGISTRY.get(name)
    if skill_cls is None:
        return None
    return {
        "name": name,
        "class_name": skill_cls.__name__,
        "class": skill_cls,
        "module": skill_cls.__module__,
    }


# ==============================================================================
# 预加载所有技能（通过导入触发注册）
# ==============================================================================

def _auto_register_skills():
    """
    自动注册所有技能（项目启动时调用一次）。
    通过相对导入触发各 skill.py 模块的 @register_skill 装饰器。
    """
    # 使用 try/except 包裹所有技能导入，防止部分技能缺失导致整体失败
    skill_imports = [
        ("router", "src.memory_palace.skills.router"),
        ("commander", "src.memory_palace.skills.commander"),
        ("memory_ops", "src.memory_palace.skills.memory_ops"),
        ("persona", "src.memory_palace.skills.persona"),
        ("watcher", "src.memory_palace.skills.watcher"),
        ("context_trigger", "src.memory_palace.skills.context_trigger"),
        ("persona_extract", "src.memory_palace.skills.persona_extract"),
        ("todo_write", "src.memory_palace.skills.todo"),
    ]

    from loguru import logger
    for skill_name, module_path in skill_imports:
        try:
            __import__(module_path)
        except ImportError as e:
            logger.warning(f"[SkillRegistry] 技能 {skill_name} 导入失败: {e}")
        except Exception as e:
            logger.warning(f"[SkillRegistry] 技能 {skill_name} 注册异常: {e}")


# ==============================================================================
# 导出
# ==============================================================================

__all__ = [
    "_SKILL_REGISTRY",
    "register_skill",
    "get_skill_by_name",
    "get_registered_skills",
    "list_skill_names",
    "is_skill_enabled",
    "enable_skill",
    "disable_skill",
    "reload_skill",
    "reload_all_skills",
    "get_skill_info",
    "_auto_register_skills",
]
