"""
TodoWrite Skill - 任务分解智能体

核心职责:
1. 接收用户的大目标描述
2. 使用 LLM 将目标分解为具体的任务列表
3. 支持任务间依赖关系
4. 将分解后的任务存入 TaskGraph

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import os
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from ...core.skill_base import BaseAgentSkill, SkillOutput, SkillValidationError
from ...core.task_graph import task_graph, TaskStatus
from ...tools.llm_wrapper import llm_client
from .. import register_skill


@register_skill("todo_write")
class TodoWriteSkill(BaseAgentSkill):
    """
    任务分解智能体

    将复杂目标分解为具有依赖关系的任务图

    输入:
        - goal: 目标描述
        - session_id: 会话 ID

    输出:
        - tasks_created: 创建的任务数量
        - task_ids: 任务 ID 列表
        - task_descriptions: 任务描述列表
    """

    DEFAULT_DECOMPOSITION_PROMPT = """你是一个任务分解专家。请将以下目标分解为具体的任务列表。

目标: {goal}

要求:
1. 每个任务应该是一个独立的、可执行的步骤
2. 任务之间如果有依赖关系，需要明确标注
3. 使用 JSON 数组格式输出
4. 每个任务包含:
   - description: 任务描述
   - depends_on: 依赖任务索引列表 (可选)
5. 最多分解为 10 个任务

输出格式:
```json
[
  {{"description": "任务1描述", "depends_on": []}},
  {{"description": "任务2描述", "depends_on": [0]}},
  ...
]
```
"""

    def __init__(self):
        self.base_path = Path(__file__).parent
        self.config = self._load_config()

        super().__init__(
            skill_name="todo_write",
            model_name=self.config.get("llm_config", {}).get("model", "gpt-4o-mini")
        )

    def _load_config(self) -> Dict[str, Any]:
        """加载配置"""
        config_path = self.base_path / "config.yaml"
        if not config_path.exists():
            return {
                "llm_config": {"model": "gpt-4o-mini"},
                "max_tasks": 10
            }

        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _validate_context(self, context: Dict[str, Any]) -> bool:
        """验证输入上下文"""
        if "goal" not in context:
            raise SkillValidationError("缺少必需字段: goal")
        if "session_id" not in context:
            raise SkillValidationError("缺少必需字段: session_id")
        return True

    async def _execute_impl(
        self,
        context: Dict[str, Any],
        trace_id: str
    ) -> SkillOutput:
        """执行任务分解"""
        goal = context.get("goal", "")
        session_id = context.get("session_id", "unknown")

        logger.info(f"[TodoWrite] 开始分解目标: {goal[:50]}...")

        try:
            # 调用 LLM 进行任务分解
            prompt = self.DEFAULT_DECOMPOSITION_PROMPT.format(goal=goal)

            llm_response = await llm_client.ask(
                system_prompt="你是一个任务分解专家。",
                user_prompt=prompt,
                temperature=0.3,
                json_mode=True,
                trace_id=trace_id
            )

            # 解析 LLM 返回的 JSON
            task_specs = await llm_client.parse_json(
                llm_response.content,
                trace_id
            )

            if not task_specs or not isinstance(task_specs, list):
                logger.error(f"[TodoWrite] LLM 返回格式错误: {llm_response.content[:200]}")
                return SkillOutput(
                    success=False,
                    error_msg="任务分解失败: LLM 返回格式错误",
                    latency_ms=0,
                    tokens_used=llm_response.tokens_used
                )

            # 创建任务图
            created_tasks = []
            task_id_map = {}  # index -> task_id 映射

            for idx, spec in enumerate(task_specs[:self.config.get("max_tasks", 10)]):
                # 消毒每个 task spec
                from ...tools.llm_wrapper import sanitize_llm_output
                spec, warns = sanitize_llm_output(spec, "task_spec", trace_id=trace_id)
                if not spec or not spec.get("description"):
                    logger.warning(f"[Trace-{trace_id}] task spec #{idx} rejected by sanitizer")
                    continue

                description = spec.get("description", "")
                depends_on_indices = spec.get("depends_on", [])

                # 转换为依赖 task_id
                dep_ids = [
                    task_id_map[idx2]
                    for idx2 in depends_on_indices
                    if idx2 in task_id_map
                ]

                # 创建任务
                task = await task_graph.create_task(
                    session_id=session_id,
                    description=description,
                    dependencies=dep_ids,
                    assigned_agent=context.get("assigned_agent")
                )

                task_id_map[idx] = task.id
                created_tasks.append(task)

                logger.debug(
                    f"[TodoWrite] 创建任务 {task.id}: {description[:30]}... "
                    f"(deps: {len(dep_ids)})"
                )

            # 返回结果
            return SkillOutput(
                success=True,
                reply_text=f"已将目标分解为 {len(created_tasks)} 个任务",
                structured_data={
                    "tasks_created": len(created_tasks),
                    "task_ids": [t.id for t in created_tasks],
                    "task_descriptions": [t.description for t in created_tasks]
                },
                action_taken="goal_decomposed",
                latency_ms=0,
                tokens_used=llm_response.tokens_used
            )

        except Exception as e:
            logger.error(f"[TodoWrite] 任务分解失败: {e}")
            return SkillOutput(
                success=False,
                error_msg=f"任务分解失败: {str(e)}"
            )


# 注册为内置 skill
# 注意: 需要在 skills/__init__.py 的 _auto_register_skills 中添加
