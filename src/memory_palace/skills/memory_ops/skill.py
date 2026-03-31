"""
处突与记忆专家智能体 (Memory Ops Skill Implementation) - 异步版本

核心变更：
1. 核心执行方法添加 async/await
2. 调用 llm_client 的地方添加 await
3. 引入 vector_client 的地方如果也是异步，需要添加 await (假设已改造)
4. 文件 IO 保持同步 (磁盘读写快，无需异步)

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import yaml
from pathlib import Path
from typing import Any, Dict, List
from loguru import logger

from ...core.skill_base import BaseAgentSkill, SkillOutput, SkillValidationError
from .. import register_skill

try:
    from ...tools.llm_wrapper import llm_client
except ImportError:
    logger.warning("llm_client 尚未实现，MemoryOps 将以模拟模式运行")
    llm_client = None

# 引入知识库的向量检索客户端
try:
    from ...knowledge.vector_store import vector_client
except ImportError:
    logger.warning("vector_client 尚未实现，MemoryOps 向量检索将以模拟模式运行")
    vector_client = None


@register_skill("memory_ops")
class MemoryOpsSkill(BaseAgentSkill):
    """
    处突与记忆专家：负责通过向量数据库打捞历史处置经验，提供决策参考 (异步版本)。
    """

    def __init__(self):
        self.base_path = Path(__file__).parent
        self.config = self._load_config()

        super().__init__(
            skill_name=self.config.get("agent_name", "MemoryOps_Agent"),
            model_name=self.config.get("llm_config", {}).get("model", "gpt-4-turbo")
        )

    def _load_config(self) -> Dict[str, Any]:
        """加载专家专属配置文件"""
        config_path = self.base_path / "config.yaml"
        if not config_path.exists():
            logger.warning("MemoryOps config 缺失，采用默认 RAG 参数。")
            return {
                "agent_name": "MemoryOps_Agent",
                "llm_config": {"model": "gpt-4-turbo"},
                "rag_config": {"top_k": 3, "similarity_threshold": 0.75}
            }

        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _load_prompt_template(self) -> str:
        """加载带有 RAG 占位符的 System Prompt"""
        prompt_path = self.base_path / "prompts" / "advice.txt"
        if not prompt_path.exists():
            raise FileNotFoundError(f"致命错误：未找到记忆专家 Prompt 模板 {prompt_path}")

        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read().strip()

    def _validate_context(self, context: Dict[str, Any]) -> None:
        """入参校验：专家只需要用户的原始提问即可进行检索"""
        if "raw_text" not in context or not str(context["raw_text"]).strip():
            raise SkillValidationError("MemoryOps 缺少核心检索词 'raw_text'。")

    def _format_retrieved_docs(self, docs: List[Dict[str, Any]]) -> str:
        """
        工业级文本拼装：将召回的多个向量文档格式化为 LLM 易读的 XML/Markdown 结构。
        """
        if not docs:
            return "【系统提示：向量知识库中未检索到相关历史案例。】"

        formatted_str = ""
        for idx, doc in enumerate(docs, 1):
            formatted_str += f"### 历史案例 {idx} (相似度: {doc.get('score', 0):.2f})\n"
            formatted_str += f"- 发生时间: {doc.get('metadata', {}).get('date', '未知')}\n"
            formatted_str += f"- 处置方案: {doc.get('content', '无详细内容')}\n\n"
        return formatted_str.strip()

    ### CHANGE: 核心方法改为 async
    async def _execute_impl(self, context: Dict[str, Any], trace_id: str) -> SkillOutput:
        """执行 RAG 检索与增强生成逻辑 (异步版本)"""
        query_text = str(context["raw_text"]).strip()
        logger.info(f"[Trace-{trace_id}] MemoryOps 启动，开始为 '{query_text}' 检索历史经验...")

        try:
            # ---------------------------------------------------------
            # 1. 向量检索 (Retrieval)
            # ---------------------------------------------------------
            rag_params = self.config.get("rag_config", {})
            top_k = rag_params.get("top_k", 3)
            threshold = rag_params.get("similarity_threshold", 0.75)

            ### CHANGE: 如果 vector_client.search 是异步，添加 await
            # 假设 vector_client 已改造为异步，如果仍是同步则保持原样
            # 注意：ChromaDB 本地查询很快，通常不需要异步，但如果封装了异步接口则使用 await
            if vector_client and hasattr(vector_client, 'asearch'):  # 优先使用异步接口
                retrieved_docs = await vector_client.asearch(
                    query=query_text,
                    top_k=top_k,
                    threshold=threshold
                )
            elif vector_client:
                # 同步调用 (ChromaDB 本地查询毫秒级，可接受)
                retrieved_docs = vector_client.search(
                    query=query_text,
                    top_k=top_k,
                    threshold=threshold
                )
            else:
                retrieved_docs = []

            logger.debug(f"[Trace-{trace_id}] 召回 {len(retrieved_docs)} 条相似历史记录。")

            knowledge_context = self._format_retrieved_docs(retrieved_docs)

            # ---------------------------------------------------------
            # 2. 组装增强生成 Prompt (Augmented Generation)
            # ---------------------------------------------------------
            template = self._load_prompt_template()
            full_system_prompt = template.format(retrieved_knowledge=knowledge_context)

            # ---------------------------------------------------------
            # 3. 调用 LLM 进行总结推理
            # ---------------------------------------------------------
            if llm_client:
                llm_params = self.config.get("llm_config", {})

                ### CHANGE: 添加 await 调用异步 LLM
                llm_res = await llm_client.ask(
                    system_prompt=full_system_prompt,
                    user_prompt=f"当前一线员工的提问/求助是：{query_text}\n请基于上述历史案例给出建议。",
                    model=self.model_name,
                    temperature=llm_params.get("temperature", 0.3),
                    json_mode=True,
                    trace_id=trace_id
                )

                # ---------------------------------------------------------
                # 4. 解析结果并返回 DTO
                # ---------------------------------------------------------
                ### CHANGE: 添加 await 调用异步解析
                advice_data = await llm_client.parse_json(llm_res.content, trace_id=trace_id)

                reply_text = advice_data.get("reply_text")
                if not retrieved_docs and not reply_text:
                    reply_text = "抱歉，记忆宫殿中暂未检索到关于此情况的历史处置案例。建议直接请示值班经理。"

                return SkillOutput(
                    success=True,
                    reply_text=reply_text,
                    structured_data={
                        "retrieved_count": len(retrieved_docs),
                        "reference_cases": [doc.get("metadata", {}).get("case_id") for doc in retrieved_docs if doc.get("metadata")],
                        "action_taken": "rag_experience_advice"
                    },
                    action_taken="rag_experience_advice",
                    tokens_used=llm_res.tokens_used
                )
            else:
                return SkillOutput(
                    success=True,
                    reply_text="记忆专家暂时离线，无法提供历史案例检索服务。",
                    structured_data={
                        "retrieved_count": 0,
                        "reference_cases": [],
                        "action_taken": "mock_rag_retrieval"
                    },
                    action_taken="mock_rag_retrieval"
                )

        except Exception as e:
            logger.error(f"[Trace-{trace_id}] MemoryOps RAG 链路执行失败: {e}")
            raise
