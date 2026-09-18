"""Guard the Agent prompt/runtime contract boundary.

The skill prompt files describe judgement only. If one of them restates an output
schema, it competes with the Pydantic contract and the model will answer in the wrong
shape - that is exactly what made the trunk retry and give up during ticket m5-05.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.memory_palace.agent_contracts.models import AgentRole
from src.memory_palace.incident.runtime import (
    PROMPT_VERSION,
    _PROMPT_FILES,
    system_prompt_for,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LEGACY_OUTPUT_KEYS = ("reply_text", "action_taken", "structured_data")
LEGACY_HEADINGS = (
    "OUTPUT SCHEMA",
    "\u8f93\u51fa\u7ea6\u675f",
    "\u8f93\u51fa\u683c\u5f0f",
    "\u8f93\u51fa\u7ed3\u6784",
)


def test_the_skill_files_may_keep_legacy_schemas_but_the_runtime_overrides_them():
    # The legacy self-built chain still loads these exact files, so their historical
    # output sections stay on disk. The trunk must neutralise them explicitly instead of
    # deleting them, otherwise the legacy Commander/Router skills lose their contract.
    for folder, relative in _PROMPT_FILES.values():
        path = PROJECT_ROOT / "src" / "memory_palace" / "skills" / folder / relative
        assert path.is_file(), path
    for role in AgentRole:
        prompt = system_prompt_for(role)
        assert "\u6700\u9ad8\u4f18\u5148\u7ea7" in prompt, role
        assert "reply_text" in prompt, role


def test_the_memory_ops_prompt_states_the_grounding_rules():
    prompt = system_prompt_for(AgentRole.MEMORY_OPS)
    assert PROMPT_VERSION in prompt
    assert "NO_EVIDENCE" in prompt
    assert "RETRIEVAL_FAILED" in prompt
    assert "\u6ca1\u6709\u4f9d\u636e" in prompt
    assert "reply_text" in prompt  # only in the explicit ban list


def test_every_role_prompt_bans_the_legacy_shape():
    for role in AgentRole:
        prompt = system_prompt_for(role)
        assert "reply_text" in prompt, role
        assert PROMPT_VERSION in prompt, role
