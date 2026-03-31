"""
Memory Palace OS - 企业微信智能调度平台
========================================

统一的 AI 原生运营平台，基于大语言模型实现景区/企业场景下的
智能分诊、处突调度、经验沉淀与人格化交互。

子包：
  - core/     核心引擎层（Gateway、Orchestrator、SkillBase）
  - skills/   特种智能体包（Router、Commander、MemoryOps、Persona、Watcher）
  - tools/    原子工具层（LLM、WeChat、向量库、熔断器等）
  - config/   配置管理（settings.yaml、registry.yaml）
  - knowledge/ 知识库层（SQLAlchemy + ChromaDB）
  - metrics/  指标与可观测性
  - api/      REST API（v1/v2）

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

__version__ = "1.0.0"
__app_name__ = "Memory Palace OS"

__all__ = ["__version__", "__app_name__"]
