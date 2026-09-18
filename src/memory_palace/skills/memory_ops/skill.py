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
from ...knowledge.evidence_backed_retrieval import (
    KnowledgeRetrievalError,
    RetrievalRequest,
)
from ...tools.llm_wrapper import llm_client
from .. import register_skill


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
            model_name=self.config.get("llm_config", {}).get("model", "deepseek-flash")
        )

    def _load_config(self) -> Dict[str, Any]:
        """加载专家专属配置文件"""
        config_path = self.base_path / "config.yaml"
        if not config_path.exists():
            logger.warning("MemoryOps config 缺失，采用默认 RAG 参数。")
            return {
                "agent_name": "MemoryOps_Agent",
                "llm_config": {"model": "deepseek-flash"},
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
            reference = doc.get("metadata") or {}
            formatted_str += (
                f"### {reference['source_label']} {idx}: {reference['title']} "
                f"(版本 {reference['version']})\n"
            )
            formatted_str += f"- 来源标识: {reference['source_id']}\n"
            formatted_str += f"- 相关度: {reference['score']:.3f}\n"
            formatted_str += f"- 已发布内容: {doc.get('content', '无详细内容')}\n\n"
        return formatted_str.strip()

    ### CHANGE: 核心方法改为 async
    async def _execute_impl(self, context: Dict[str, Any], trace_id: str) -> SkillOutput:
        """执行 RAG 检索与增强生成逻辑 (异步版本)"""
        query_text = str(context["raw_text"]).strip()
        logger.info(f"[Trace-{trace_id}] MemoryOps 启动，开始为 '{query_text}' 检索历史经验...")

        try:
            if not llm_client:
                raise RuntimeError("MemoryOps LLM 客户端未初始化，不能生成检索建议")

            rag_params = self.config.get("rag_config", {})
            top_k = rag_params.get("top_k", 3)
            threshold = rag_params.get("similarity_threshold", 0.75)

            retriever = context.get("_knowledge_retriever")
            if retriever is None:
                raise RuntimeError("MemoryOps 证据检索模块未注入")
            try:
                retrieval = await retriever.retrieve(
                    RetrievalRequest(
                        query=query_text,
                        venue_id=str(context.get("venue_id") or ""),
                        trace_id=trace_id,
                        user_id=str(context.get("from_user") or ""),
                        message_id=str(context.get("msg_id") or "") or None,
                        session_id=str(context.get("session_id") or "") or None,
                        agent_id="MemoryOps",
                        top_k=int(top_k),
                        similarity_threshold=float(threshold),
                    )
                )
            except KnowledgeRetrievalError as exc:
                return SkillOutput(
                    success=False,
                    reply_text="知识检索当前不可用，请由值班经理人工核验。",
                    structured_data={
                        "retrieval_snapshot_id": exc.snapshot_id,
                        "retrieval_status": "FAILED",
                        "retrieved_count": 0,
                        "references": [],
                        "action_taken": "knowledge_retrieval_failed",
                    },
                    action_taken="knowledge_retrieval_failed",
                    error_msg="知识检索失败，未返回任何未经确权的引用",
                )
            retrieved_docs = list(retrieval.documents)
            references = [dict(reference) for reference in retrieval.references]

            logger.debug(
                f"[Trace-{trace_id}] 召回并确权 {len(retrieved_docs)} 条知识记录，"
                f"快照 {retrieval.snapshot_id}。"
            )

            knowledge_context = self._format_retrieved_docs(retrieved_docs)
            template = self._load_prompt_template()
            full_system_prompt = template.format(retrieved_knowledge=knowledge_context)

            llm_params = self.config.get("llm_config", {})
            llm_res = await llm_client.ask(
                system_prompt=full_system_prompt,
                user_prompt=f"当前一线员工的提问/求助是：{query_text}\n请基于上述历史案例给出建议。",
                model=self.model_name,
                temperature=llm_params.get("temperature", 0.3),
                json_mode=True,
                trace_id=trace_id,
                venue_id=context.get("venue_id", ""),
                agent_id="MemoryOps",
                agent_name=self.skill_name,
            )

            advice_data = await llm_client.parse_json(llm_res.content, trace_id=trace_id)
            if not isinstance(advice_data, dict) or not str(advice_data.get("reply_text", "")).strip():
                raise ValueError("MemoryOps LLM 返回结果缺少有效 reply_text")

            return SkillOutput(
                success=True,
                reply_text=advice_data["reply_text"],
                structured_data={
                    "retrieval_snapshot_id": retrieval.snapshot_id,
                    "retrieval_status": retrieval.status,
                    "retrieved_count": len(references),
                    "references": references,
                    "action_taken": "rag_experience_advice",
                },
                action_taken="rag_experience_advice",
                tokens_used=llm_res.tokens_used,
            )

        except Exception as e:
            logger.error(f"[Trace-{trace_id}] MemoryOps RAG 链路执行失败: {e}")
            raise
