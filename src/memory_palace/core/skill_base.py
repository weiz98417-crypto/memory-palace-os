"""
智能体核心抽象基类 (Agent Skill Base)

本模块定义了系统中所有智能体（Router, Commander, MemoryOps 等）的最高行为准则。
采用"模板方法模式 (Template Method Pattern)"，强制物理隔离数据校验、执行逻辑与统一输出。
杜绝大模型在执行过程中产生的随意返回、格式失控和系统级崩溃。

与原版的差异（v2）：
  1. run() / _execute_impl() 改为 async — 兼容 FastAPI asyncio 事件循环，
     防止 LLM 网络 IO 阻塞全局消息队列
  2. 新增 load_prompt() — 自动检测 prompts/soul.txt 并前置注入，
     实现 Agent 人格与任务指令的解耦
  3. _validate_context() 保持同步 — 纯内存校验无 IO，不需要 async

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import abc
import asyncio
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger
from pydantic import BaseModel, Field


# =============================================================================
# 1. 自定义异常类 (Custom Exceptions)
# =============================================================================

class SkillValidationError(Exception):
    """
    业务级校验异常。
    当流入智能体的上下文 (Context) 缺少必要字段或脏数据时抛出。
    此异常不会触发系统熔断报警，只会优雅阻断当前调用。
    """
    pass


# =============================================================================
# 2. 标准输出契约 DTO (Data Transfer Object)
# =============================================================================

class SkillOutput(BaseModel):
    """
    工业级标准输出结构。
    强制所有子类智能体必须以此统一的强类型格式，将结果返回给调度中枢 (Orchestrator)。
    任何非该结构的返回值，都将在 Python 运行时被类型系统拦截。
    """
    success: bool = Field(..., description="智能体本次流转是否成功完成")

    reply_text: Optional[str] = Field(
        None,
        description="需要直接回复给企微用户的最终文本/Markdown"
    )
    structured_data: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="大模型提取的结构化数据（如路由意图、抽取的表单实体等）"
    )

    action_taken: Optional[str] = Field(
        None,
        description="智能体执行的具体动作标识（用于审计追踪）"
    )
    error_msg: Optional[str] = Field(
        None,
        description="失败时的前端友好报错信息"
    )

    # ── 可观测性度量指标 (Observability Metrics) ──────────────────────────────
    latency_ms: int = Field(0, description="大模型网络请求与推理的总耗时 (毫秒)")
    tokens_used: int = Field(0, description="本次处理消耗的整体 Token 数，用于系统成本审计")


# =============================================================================
# 3. 核心抽象基类 (Abstract Base Class)
# =============================================================================

class BaseAgentSkill(abc.ABC):
    """
    5 大特种智能体的最高抽象基类。
    外部调度中枢只允许调用 `run()` 方法，绝不允许直接调用内部实现。

    Soul 注入机制：
      每个 skill 的 prompts/ 目录下可放 soul.txt。
      load_prompt("prompts/xxx.txt") 会自动检测并前置拼接：

        [SOUL]
        <soul 内容>
        [/SOUL]

        ---任务指令开始---
        <任务 prompt 内容>
    """

    def __init__(self, skill_name: str, model_name: str = "gpt-3.5-turbo"):
        self.skill_name = skill_name
        self.model_name = model_name
        self._prompt_cache: dict[str, str] = {}

    # =========================================================================
    # 模板方法入口（唯一对外接口）
    # =========================================================================

    async def run(self, context: Dict[str, Any], trace_id: str = "UNKNOWN") -> SkillOutput:
        """
        【模板方法】外部调度的唯一合法入口。
        内部自动封装：高精度耗时统计、防崩溃全局异常捕获、前置安全护栏。

        ⚠️  async 说明：
          LLM 调用是网络 IO（10-30s），必须是 async 才不会阻塞 asyncio 事件循环。
          同步版本会导致整个消息队列在 LLM 推理期间全部冻结。

        :param context:  从企微或上游智能体传递来的上下文数据字典
        :param trace_id: 全链路追踪 ID，用于日志染色串联
        :return:         SkillOutput 强类型标准输出
        """
        start_time = time.time()
        logger.info(
            f"[Trace-{trace_id}] 🟢 [Skill: {self.skill_name}] 任务挂载启动。"
            f"注入上下文 Keys: {list(context.keys())}"
        )

        try:
            # ── 护栏 1：强制参数预检（同步，纯内存，无 IO）────────────────────
            self._validate_context(context)

            # ── 护栏 2：核心业务执行（async，含 LLM 网络 IO）───────────────────
            result: SkillOutput = await self._execute_impl(context, trace_id=trace_id)

            # 校验子类开发者是否遵守纪律
            if not isinstance(result, SkillOutput):
                raise TypeError(
                    f"[{self.skill_name}] _execute_impl 必须返回 SkillOutput 对象，"
                    f"实际返回: {type(result)}"
                )

            # ── 基建 3：自动装载链路监控数据 ────────────────────────────────────
            result.latency_ms = int((time.time() - start_time) * 1000)
            logger.info(
                f"[Trace-{trace_id}] 🔴 [Skill: {self.skill_name}] 执行完毕 | "
                f"Status: {result.success} | 耗时: {result.latency_ms}ms | "
                f"Token消耗: {result.tokens_used}"
            )
            return result

        except SkillValidationError as ve:
            # 业务级校验拦截（静默处理，正常流转）
            latency = int((time.time() - start_time) * 1000)
            logger.warning(
                f"[Trace-{trace_id}] 🟡 [Skill: {self.skill_name}] "
                f"上下文校验拦截: {ve}"
            )
            return SkillOutput(
                success=False,
                error_msg=f"参数校验失败: {str(ve)}",
                action_taken="validation_failed",
                latency_ms=latency,
            )

        except Exception as e:
            # 系统级致命崩溃（API 熔断、断网、JSON 解析炸裂），生成安全兜底结构
            latency = int((time.time() - start_time) * 1000)
            logger.error(
                f"[Trace-{trace_id}] ❌ [Skill: {self.skill_name}] "
                f"系统级致命崩溃: {e}\n{traceback.format_exc()}"
            )
            return SkillOutput(
                success=False,
                reply_text="系统正忙，请稍后再试。(内部状态：Agent 熔断)",
                error_msg=f"内部致命错误: {str(e)}",
                action_taken="fatal_error_fallback",
                latency_ms=latency,
            )

    # =========================================================================
    # Soul 注入 · Prompt 加载
    # =========================================================================

    def load_prompt(self, prompt_file: str) -> str:
        """
        加载任务 prompt，自动检测同目录下的 soul.txt 并前置拼接。

        目录约定：
          prompts/
            soul.txt    ← Agent 人格灵魂（可选）
            router.txt  ← 任务指令（必须）

        拼接格式：
          [SOUL]
          ...soul 内容...
          [/SOUL]

          ---任务指令开始---
          ...任务 prompt 内容...

        已实现文件级缓存，同一文件只读一次磁盘。
        热更新时调用 invalidate_prompt_cache() 清除缓存。
        """
        if prompt_file in self._prompt_cache:
            return self._prompt_cache[prompt_file]

        task_path = Path(prompt_file)
        if not task_path.exists():
            logger.warning(f"[{self.skill_name}] prompt 文件不存在: {prompt_file}")
            return ""

        task_prompt = task_path.read_text(encoding="utf-8").strip()

        soul_path = task_path.parent / "soul.txt"
        if soul_path.exists():
            soul_content = soul_path.read_text(encoding="utf-8").strip()
            full_prompt = (
                f"[SOUL]\n{soul_content}\n[/SOUL]\n\n"
                f"---任务指令开始---\n{task_prompt}"
            )
            logger.debug(f"[{self.skill_name}] soul.txt 已注入 ({len(soul_content)} 字符)")
        else:
            full_prompt = task_prompt

        self._prompt_cache[prompt_file] = full_prompt
        return full_prompt

    def invalidate_prompt_cache(self):
        """热更新 soul/prompt 文件后调用，强制下次重新读取磁盘。"""
        self._prompt_cache.clear()
        logger.info(f"[{self.skill_name}] prompt 缓存已清除")

    # =========================================================================
    # 抽象契约：子类必须实现
    # =========================================================================

    @abc.abstractmethod
    def _validate_context(self, context: Dict[str, Any]) -> None:
        """
        子类强制契约 1：数据清洗与准入校验（同步）。
        检查 context 是否包含 LLM 需要的字段，不满足则 raise SkillValidationError。

        Example:
            if "raw_text" not in context:
                raise SkillValidationError("缺少用户原始输入文本 'raw_text'")
        """
        pass

    @abc.abstractmethod
    async def _execute_impl(self, context: Dict[str, Any], trace_id: str) -> SkillOutput:
        """
        子类强制契约 2：核心业务逻辑（async）。
        在此进行 Prompt 组装、大模型接口调用、结果 JSON 解析。
        无论成功与否，最终必须返回完整的 SkillOutput 对象。

        :param context:  已通过预检的数据字典
        :param trace_id: 日志追踪 ID
        :return:         SkillOutput
        """
        pass