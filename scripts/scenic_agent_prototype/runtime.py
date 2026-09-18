"""Real four-agent prototype for the scenic Agent trunk."""

from __future__ import annotations

import os
import time
from typing import Any

import litellm
from pydantic_ai import Agent, PromptedOutput
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    SystemPromptPart,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage
from .contracts import (
    CommanderOutput,
    ContextTriggerOutput,
    MemoryOpsOutput,
    PrototypeRequest,
    PrototypeResult,
    RouterOutput,
    build_call_record,
)
from .db import PrototypeDB, secret_from_env, tei_embed


def _to_chat_messages(messages, agent_info) -> list[dict[str, str]]:
    system_parts = [str(agent_info.instructions or "")]
    for message in messages:
        if isinstance(message, ModelRequest):
            system_parts.extend(part.content for part in message.parts if isinstance(part, SystemPromptPart))
    converted: list[dict[str, str]] = []
    system_prompt = "\n\n".join(part for part in system_parts if part)
    if system_prompt:
        converted.append({"role": "system", "content": system_prompt})
    for message in messages:
        if isinstance(message, ModelRequest):
            for part in message.parts:
                if isinstance(part, UserPromptPart):
                    converted.append({"role": "user", "content": str(part.content)})
                elif isinstance(part, RetryPromptPart):
                    converted.append({"role": "user", "content": str(part.content)})
        elif isinstance(message, ModelResponse):
            text = "\n".join(part.content for part in message.parts if isinstance(part, TextPart))
            if text:
                converted.append({"role": "assistant", "content": text})
    return converted


async def _litellm_chat(messages, agent_info) -> ModelResponse:
    model_name = os.environ.get("SCENIC_AGENT_MODEL") or os.environ.get("LLM_DEFAULT_MODEL", "deepseek-flash")
    response = await litellm.acompletion(
        model=f"openai/{model_name}",
        api_base=os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com/v1",
        api_key=secret_from_env("DEEPSEEK_API_KEY"),
        messages=_to_chat_messages(messages, agent_info),
        temperature=0,
        max_tokens=2000,
    )
    usage = response.usage
    content = response.choices[0].message.content or ""
    return ModelResponse(
        parts=[TextPart(content)],
        usage=RequestUsage(
            input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
        ),
        model_name=str(getattr(response, "model", model_name) or model_name),
        provider_response_id=str(getattr(response, "id", "") or "") or None,
    )


def build_model():
    model_name = os.environ.get("SCENIC_AGENT_MODEL") or os.environ.get("LLM_DEFAULT_MODEL", "deepseek-flash")
    return FunctionModel(_litellm_chat, model_name=model_name)


def build_agents(model) -> dict[str, Agent[Any, Any]]:
    return {
        "context_trigger": Agent(
            model,
            output_type=PromptedOutput(ContextTriggerOutput),
            system_prompt="你负责装配并归一化景区事件上下文，只返回结构化 JSON。",
        ),
        "router": Agent(
            model,
            output_type=PromptedOutput(RouterOutput),
            system_prompt="你负责判断景区事件意图、风险等级和风险码，只返回结构化 JSON。",
        ),
        "memory_ops": Agent(
            model,
            output_type=PromptedOutput(MemoryOpsOutput),
            system_prompt=(
                "你是景区知识处置 agent。只能使用输入中已核验的 SOP；"
                "没有 SOP 时必须有“没有依据”且 citations 为空；有 SOP 时 citation.source_id/title/version 必须逐字来自输入。"
            ),
        ),
        "commander": Agent(
            model,
            output_type=PromptedOutput(CommanderOutput),
            system_prompt=(
                "你负责根据前序结果生成派单草案。停运、启用备用车、解除风险等高风险动作必须 "
                "requires_human_approval=true；不能执行决定，只返回结构化 JSON。"
            ),
        ),
    }


class PydanticAIPrototypeCommand:
    def __init__(self, *, model=None, tei_base_url: str | None = None) -> None:
        self.model = model or build_model()
        self.agents = build_agents(self.model)
        self.tei_base_url = tei_base_url or os.environ.get("SCENIC_TEI_EMBEDDING_URL", "http://tei-embedding:80")

    async def execute(
        self,
        request: PrototypeRequest,
        *,
        db: PrototypeDB,
        tracer,
    ) -> PrototypeResult:
        sop = await db.fetch_sop(request.venue_id, str(request.sop_hit["source_id"]))
        if not sop:
            raise RuntimeError("verified SOP is missing or no longer published")
        query_vector = await tei_embed(self.tei_base_url, request.query)
        candidates = await db.query_tei_sop_candidates(
            venue_id=request.venue_id,
            query_vector=query_vector,
            limit=5,
        )
        if not candidates:
            raise RuntimeError("TEI/pgvector returned no verified SOP candidates")
        top = candidates[0]
        if str(top["source_id"]) != str(request.sop_hit["source_id"]):
            raise RuntimeError(
                "TEI top SOP does not match the persisted verified hit: "
                f"{top['source_id']} != {request.sop_hit['source_id']}"
            )

        context = {
            "incident": {
                "incident_id": request.incident_id,
                "event_id": request.event_id,
                "title": request.incident_title,
                "priority": request.priority,
                "query": request.query,
            },
            "field_evidence": request.field_evidence,
            "verified_sop": {
                "source_id": str(sop["id"]),
                "title": sop["title"],
                "version": sop["version"],
                "content": str(sop["content"])[:3000],
            },
        }

        with tracer.start_as_current_span(
            "scenic.incident_command",
            attributes={
                "memory_palace.venue_id": request.venue_id,
                "memory_palace.incident_id": request.incident_id,
                "memory_palace.event_id": request.event_id,
            },
        ) as root_span:
            trace_id = f"{root_span.get_span_context().trace_id:032x}"
            context_output, context_call = await self._run_agent(
                "context_trigger",
                context,
                request=request,
                db=db,
                tracer=tracer,
                trace_id=trace_id,
            )
            router_output, router_call = await self._run_agent(
                "router",
                {
                    **context,
                    "context": context_output.model_dump(),
                },
                request=request,
                db=db,
                tracer=tracer,
                trace_id=trace_id,
            )
            memory_output, memory_call = await self._run_agent(
                "memory_ops",
                {
                    **context,
                    "context": context_output.model_dump(),
                    "router": router_output.model_dump(),
                },
                request=request,
                db=db,
                tracer=tracer,
                trace_id=trace_id,
            )
            if memory_output.evidence_status == "GROUNDED":
                valid_citations = {
                    (str(sop["id"]), str(sop["title"]), str(sop["version"])),
                }
                for citation in memory_output.citations:
                    key = (citation.source_id, citation.title, citation.version)
                    if key not in valid_citations:
                        raise RuntimeError(f"memory_ops returned an unverified citation: {key}")
            commander_output, commander_call = await self._run_agent(
                "commander",
                {
                    **context,
                    "context": context_output.model_dump(),
                    "router": router_output.model_dump(),
                    "memory_ops": memory_output.model_dump(),
                },
                request=request,
                db=db,
                tracer=tracer,
                trace_id=trace_id,
            )

        return PrototypeResult(
            incident_id=request.incident_id,
            event_id=request.event_id,
            trace_id=trace_id,
            context=context_output,
            router=router_output,
            memory_ops=memory_output,
            commander=commander_output,
            call_record_ids=[
                context_call["id"],
                router_call["id"],
                memory_call["id"],
                commander_call["id"],
            ],
            tei_evidence={
                "status": "VERIFIED",
                "model_name": "BAAI/bge-m3",
                "dimension": len(query_vector),
                "top_source_id": str(top["source_id"]),
                "top_score": float(top["similarity"]),
                "verified_source_id": str(request.sop_hit["source_id"]),
            },
        )

    async def _run_agent(
        self,
        role: str,
        payload: dict[str, Any],
        *,
        request: PrototypeRequest,
        db: PrototypeDB,
        tracer,
        trace_id: str,
    ) -> tuple[Any, dict[str, Any]]:
        agent = self.agents[role]
        with tracer.start_as_current_span(
            f"scenic.agent.{role}",
            attributes={
                "memory_palace.agent.id": role,
                "memory_palace.incident_id": request.incident_id,
            },
        ) as agent_span:
            started = time.perf_counter()
            with tracer.start_as_current_span(
                "gen_ai.chat",
                attributes={
                    "gen_ai.system": "deepseek",
                    "gen_ai.request.model": os.environ.get(
                        "SCENIC_AGENT_MODEL",
                        os.environ.get("LLM_DEFAULT_MODEL", "deepseek-flash"),
                    ),
                    "memory_palace.agent.id": role,
                },
            ) as call_span:
                result = await agent.run("请处理以下景区事件上下文，并严格按要求返回 JSON：\n" + _json(payload))
                latency_seconds = time.perf_counter() - started
            usage = result.usage
            last_message = result.all_messages()[-1]
            model_name = str(getattr(last_message, "model_name", "") or "")
            request_id = str(getattr(last_message, "provider_response_id", "") or "") or None
            call_record = build_call_record(
                venue_id=request.venue_id,
                incident_id=request.incident_id,
                mode=request.mode,
                attempt=request.attempt,
                agent_role=role,
                agent_name=role,
                provider="deepseek",
                model_name=model_name,
                request_id=request_id,
                prompt_tokens=int(getattr(usage, "input_tokens", 0) or 0),
                completion_tokens=int(getattr(usage, "output_tokens", 0) or 0),
                latency_seconds=latency_seconds,
                trace_id=trace_id,
                is_mock=False,
            )
            await db.insert_model_call(call_record)
            call_span.set_attribute("gen_ai.response.model", model_name)
            call_span.set_attribute("gen_ai.usage.input_tokens", int(getattr(usage, "input_tokens", 0) or 0))
            call_span.set_attribute("gen_ai.usage.output_tokens", int(getattr(usage, "output_tokens", 0) or 0))
            call_span.set_attribute("memory_palace.call_id", call_record["id"])
            agent_span.set_attribute("memory_palace.call_id", call_record["id"])
        return result.output, call_record


def _json(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True)
