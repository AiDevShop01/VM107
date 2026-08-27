"""Phase 167 Plan 02 (AGV-02) — Constitution preamble system_prompt extension tests.

RED-first: imports ``ConstitutionPreamble`` + ``render_constitution_preamble`` from
the not-yet-created ``_06_constitution_preamble`` module (ImportError until Task 2).

Mirrors the ``_05_tool_scope_filter`` no-op discipline (three guards: string profile /
dict-without-key / no agent) and asserts a SINGLE injection at ``system_prompt[0]``.
Uses a mocked agent context (no live VM107 boot) — matches the ``phase89_1`` stub style.
"""
from __future__ import annotations

import pathlib
import sys
from typing import Any

import pytest

_VM107_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

from extensions.python.system_prompt._06_constitution_preamble import (  # noqa: E402
    ConstitutionPreamble,
    render_constitution_preamble,
)

_SKILLS = ["citation-discipline", "narrative-only-explain"]


def _make_agent_stub(profile: Any):
    """Minimal agent stub mirroring the production Agent surface the extension touches.

    Only ``.profile`` and ``.context.log.log(**kwargs)`` are exercised.
    """

    class _Log:
        @staticmethod
        def log(**kwargs):
            pass

    class _Ctx:
        log = _Log()

    class _AgentStub:
        def __init__(self, p: Any):
            self.profile = p
            self.context = _Ctx()

    return _AgentStub(profile)


@pytest.mark.asyncio
async def test_injects_when_constitutional_skills_present():
    """dict profile carrying constitutional_skills → ONE preamble at system_prompt[0]."""
    agent = _make_agent_stub({"constitutional_skills": _SKILLS})
    ext = ConstitutionPreamble(agent)
    system_prompt: list[str] = ["MAIN PROMPT BODY"]

    await ext.execute(system_prompt=system_prompt)

    assert len(system_prompt) == 2, "exactly one preamble entry inserted"
    assert system_prompt[1] == "MAIN PROMPT BODY", "existing body preserved after preamble"
    assert isinstance(system_prompt[0], str) and system_prompt[0], "preamble is a non-empty string"


@pytest.mark.asyncio
async def test_noop_on_string_profile():
    """Legacy string profile → extension is a no-op (zero blast radius)."""
    agent = _make_agent_stub("legacy-string-profile")
    ext = ConstitutionPreamble(agent)
    system_prompt = ["MAIN"]

    await ext.execute(system_prompt=system_prompt)

    assert system_prompt == ["MAIN"], "string profile must not inject"


@pytest.mark.asyncio
async def test_noop_on_dict_without_key():
    """dict profile lacking constitutional_skills → explicit no-op."""
    agent = _make_agent_stub({"allowed_tools": ["x"]})
    ext = ConstitutionPreamble(agent)
    system_prompt = ["MAIN"]

    await ext.execute(system_prompt=system_prompt)

    assert system_prompt == ["MAIN"], "dict without constitutional_skills must not inject"


@pytest.mark.asyncio
async def test_noop_when_no_agent():
    """self.agent is None → no-op, no raise."""
    ext = ConstitutionPreamble(None)
    system_prompt = ["MAIN"]

    await ext.execute(system_prompt=system_prompt)

    assert system_prompt == ["MAIN"], "no agent must not inject or raise"


@pytest.mark.asyncio
async def test_single_injection_not_per_rule():
    """The 19 rules land as ONE block, not one entry per rule."""
    agent = _make_agent_stub({"constitutional_skills": _SKILLS})
    ext = ConstitutionPreamble(agent)
    system_prompt: list[str] = []

    await ext.execute(system_prompt=system_prompt)

    assert len(system_prompt) == 1, "single block injected, never one-per-rule"

    # render_constitution_preamble is the single versioned source; deterministic for
    # a given skills list, so the injected entry equals it exactly and appears once.
    preamble = render_constitution_preamble(_SKILLS)
    assert isinstance(preamble, str)
    assert system_prompt[0] == preamble
    assert system_prompt.count(preamble) == 1
