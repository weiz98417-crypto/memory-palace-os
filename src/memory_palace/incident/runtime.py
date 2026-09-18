"""Production Agent runtime for the scenic trunk.

Four pydantic-ai agents share one model. The model adapter goes through LiteLLM in
process because `deepseek-flash` is a thinking model that rejects `tool_choice` and
native JSON-schema `response_format` (ticket 08), so structured output uses
`PromptedOutput` plus Pydantic validation/retry.

Prompts live in each skill directory; this module only loads and wires them.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

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

from ..agent_contracts.models import AgentRole
from ..skills.commander.contracts import CommanderOutput
from ..skills.context_trigger.contracts import ContextTriggerOutput
from ..skills.memory_ops.contracts import MemoryOpsOutput
from ..skills.router.contracts import RouterOutput

PROMPT_VERSION = "scenic-agent-trunk-v1"
DEFAULT_MODEL_ENV = "SCENIC_AGENT_MODEL"
SKILLS_ROOT = Path(__file__).resolve().parents[1] / "skills"

_OUTPUT_INSTRUCTION = (
    "\n\n## \u8f93\u51fa\u5951\u7ea6\uff08\u6700\u9ad8\u4f18\u5148\u7ea7\uff0c\u8986\u76d6\u4e0a\u6587\uff09\n"
    "\u4e0a\u6587\u6280\u80fd\u6587\u4ef6\u91cc\u5199\u7684\u4efb\u4f55\u201c\u8f93\u51fa\u683c\u5f0f\u201d\u6216 JSON \u793a\u4f8b\u5747\u5df2\u4f5c\u5e9f\uff0c"
    "\u5b83\u4eec\u662f\u65e7\u7cfb\u7edf\u7684\u9057\u7559\u6587\u672c\uff0c\u4e0d\u662f\u672c\u6b21\u8c03\u7528\u7684\u8981\u6c42\u3002"
    "\u4f60\u5fc5\u987b\u4e25\u683c\u6309\u672c\u6b21\u8c03\u7528\u9644\u4ef6\u7ed9\u51fa\u7684 JSON Schema \u8f93\u51fa\uff1a"
    "\u5b57\u6bb5\u540d\u3001\u7c7b\u578b\u4e0e\u679a\u4e3e\u503c\u5b8c\u5168\u4e00\u81f4\uff0c\u4e0d\u5141\u8bb8\u4efb\u4f55\u989d\u5916\u5b57\u6bb5\u3002\n"
    "\u7279\u522b\u6ce8\u610f\uff1a\u4e0d\u8981\u8f93\u51fa `reply_text`\u3001`action_taken`\u3001`structured_data`\u3001`required_tools`\u3001"
    "`next_step_check`\u3001`immediate_actions` \u8fd9\u7c7b\u65e7\u5b57\u6bb5\uff0c\u9664\u975e\u672c\u6b21\u8c03\u7528\u7684 Schema \u91cc\u660e\u786e\u8981\u6c42\u3002\n"
    "\u53ea\u8f93\u51fa\u4e00\u4e2a JSON \u5bf9\u8c61\uff0c\u4e0d\u8981 Markdown \u4ee3\u7801\u5757\u3001\u4e0d\u8981\u524d\u540e\u8bf4\u660e\u3002"
)

_PROMPT_FILES = {
    AgentRole.CONTEXT_TRIGGER: ("context_trigger", "prompts/trigger.txt"),
    AgentRole.ROUTER: ("router", "soul.txt"),
    AgentRole.MEMORY_OPS: ("memory_ops", "prompts/advice.txt"),
    AgentRole.COMMANDER: ("commander", "prompts/dispatch.txt"),
}

# Contract-level rules the model must be told explicitly; they are enforced by the
# Pydantic models anyway, so a violation only wastes a retry.
_ROLE_RULES = {
    AgentRole.MEMORY_OPS: (
        "\n\n## \u7ea6\u675f\u63d0\u793a\n"
        "- \u53ea\u8981\u6ca1\u6709\u5df2\u6838\u9a8c\u7684\u547d\u4e2d\uff08\u65e0 SOP\u3001\u65e0\u5df2\u5ba1\u7ecf\u9a8c\u3001\u65e0\u5386\u53f2\u6848\u4f8b\uff09\uff0c"
        "\u5c31\u5fc5\u987b\u8f93\u51fa `evidence_status='NO_EVIDENCE'`\uff0c"
        "\u4e14 `advice_text` \u5fc5\u987b\u6070\u597d\u662f\u56db\u4e2a\u5b57\u201c\u6ca1\u6709\u4f9d\u636e\u201d\uff0c"
        "`citations` \u5fc5\u987b\u662f\u7a7a\u6570\u7ec4\uff1b\u4e0d\u8981\u81ea\u5df1\u5199\u5176\u4ed6\u62d2\u7b54\u53e5\u5b50\u3002\n"
        "- \u53ea\u6709\u5b58\u5728\u5df2\u6838\u9a8c\u547d\u4e2d\u65f6\u624d\u80fd\u8f93\u51fa `evidence_status='GROUNDED'`\uff0c"
        "\u4e14 `citations[].source_id` \u53ea\u80fd\u53d6\u81ea\u8f93\u5165\u7684\u5df2\u6838\u9a8c\u6765\u6e90\u3002\n"
        "- \u6a21\u578b\u672c\u8eab\u4e0d\u53ef\u7528\u65f6\u8f93\u51fa "
        "`evidence_status='RETRIEVAL_FAILED'` + `advice_text` \u6070\u597d\u4e3a\u201c\u672a\u83b7\u5f97\u6a21\u578b\u5efa\u8bae\u201d\u3002"
    ),
}


def _model_name() -> str:
    return (
        os.environ.get(DEFAULT_MODEL_ENV)
        or os.environ.get("LLM_DEFAULT_MODEL")
        or "deepseek-flash"
    )


def _api_key() -> str:
    inline = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if inline:
        return inline
    secret_path = os.environ.get("DEEPSEEK_API_KEY_FILE", "").strip()
    if secret_path:
        return Path(secret_path).read_text(encoding="utf-8").strip()
    return ""


def system_prompt_for(role: AgentRole) -> str:
    """Load the role prompt from its skill directory, then append the JSON contract."""

    folder, relative = _PROMPT_FILES[role]
    path = SKILLS_ROOT / folder / relative
    try:
        base = path.read_text(encoding="utf-8").strip()
    except OSError:
        base = f"\u4f60\u662f\u666f\u533a Agent \u4e3b\u5e72\u7684 {role.value} \u73af\u8282\u3002"
    return (
        f"{base}{_ROLE_RULES.get(role, '')}\n\n"
        f"\u63d0\u793a\u8bcd\u7248\u672c\uff1a{PROMPT_VERSION}\u3002"
        f"{_OUTPUT_INSTRUCTION}"
    )


def _to_chat_messages(messages: Any, agent_info: Any) -> list[dict[str, str]]:
    system_parts = [str(getattr(agent_info, "instructions", "") or "")]
    for message in messages:
        if isinstance(message, ModelRequest):
            system_parts.extend(
                str(part.content)
                for part in message.parts
                if isinstance(part, SystemPromptPart)
            )
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
            text = "\n".join(
                str(part.content)
                for part in message.parts
                if isinstance(part, TextPart)
            )
            if text:
                converted.append({"role": "assistant", "content": text})
    return converted


def _temperature() -> float:
    raw = os.environ.get("SCENIC_AGENT_TEMPERATURE", "0")
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _max_tokens() -> int:
    raw = os.environ.get("SCENIC_AGENT_MAX_TOKENS", "2000")
    try:
        return int(raw)
    except ValueError:
        return 2000


def build_litellm_function_model(model_name: str | None = None) -> FunctionModel:
    """pydantic-ai model adapter that routes every call through LiteLLM in process."""

    resolved = model_name or _model_name()

    async def call(messages: Any, agent_info: Any) -> ModelResponse:
        import litellm

        response = await litellm.acompletion(
            model=f"openai/{resolved}",
            api_base=os.environ.get("DEEPSEEK_BASE_URL")
            or "https://api.deepseek.com/v1",
            api_key=_api_key(),
            messages=_to_chat_messages(messages, agent_info),
            temperature=_temperature(),
            max_tokens=_max_tokens(),
        )
        usage = getattr(response, "usage", None)
        content = response.choices[0].message.content or ""
        response_model_name = str(getattr(response, "model", "") or resolved)
        return ModelResponse(
            parts=[TextPart(content)],
            usage=RequestUsage(
                input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            ),
            model_name=response_model_name,
            provider_response_id=str(getattr(response, "id", "") or "") or None,
        )

    return FunctionModel(call, model_name=resolved)


def build_incident_agents(
    model: Any = None,
) -> dict[AgentRole, Any]:
    """Build the four trunk agents against one shared model."""

    shared_model = model or build_litellm_function_model()
    return {
        AgentRole.CONTEXT_TRIGGER: Agent(
            shared_model,
            output_type=PromptedOutput(ContextTriggerOutput),
            system_prompt=system_prompt_for(AgentRole.CONTEXT_TRIGGER),
        ),
        AgentRole.ROUTER: Agent(
            shared_model,
            output_type=PromptedOutput(RouterOutput),
            system_prompt=system_prompt_for(AgentRole.ROUTER),
        ),
        AgentRole.MEMORY_OPS: Agent(
            shared_model,
            output_type=PromptedOutput(MemoryOpsOutput),
            system_prompt=system_prompt_for(AgentRole.MEMORY_OPS),
        ),
        AgentRole.COMMANDER: Agent(
            shared_model,
            output_type=PromptedOutput(CommanderOutput),
            system_prompt=system_prompt_for(AgentRole.COMMANDER),
        ),
    }


class DictIncidentAgentRegistry:
    """Resolves the trunk agents by role."""

    def __init__(self, agents: dict[AgentRole, Any]) -> None:
        missing = [role for role in AgentRole if role not in agents]
        if missing:
            raise ValueError(f"missing incident agents: {[role.value for role in missing]}")
        self._agents = dict(agents)

    def resolve(self, role: AgentRole) -> Any:
        return self._agents[role]


def build_incident_agent_registry() -> DictIncidentAgentRegistry:
    return DictIncidentAgentRegistry(build_incident_agents())


__all__ = [
    "DEFAULT_MODEL_ENV",
    "DictIncidentAgentRegistry",
    "PROMPT_VERSION",
    "build_incident_agent_registry",
    "build_incident_agents",
    "build_litellm_function_model",
    "system_prompt_for",
]
