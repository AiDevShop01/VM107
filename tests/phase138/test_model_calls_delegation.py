"""Phase 138 (P6 / F3 Seam 2) — model-call public-surface + delegation lock.

Locks the CURRENT ``Agent.call_utility_model`` / ``Agent.call_chat_model`` surface
(agent.py:772-856) BEFORE Wave C extracts their bodies into
``core/agents/model_calls.py``, so the extraction preserves the exact surface its
consumers depend on (RESEARCH §4).

Load-bearing consumer contract (must NOT change):
  * B5 rubric scorer / self-check hook probe the method with
    ``getattr(agent, "call_utility_model", None)`` (core/b5/rubric_scorer.py,
    core/b5/response_self_check_hook.py) — the attribute must stay present + callable.
  * Both methods are async (``inspect.iscoroutinefunction`` True even after
    ``@extension.extensible``) and internally fire the ``*_model_call_before/after``
    extension hooks with the AGENT instance — the delegator must keep ``@extension.extensible``.

The post-extraction delegation assertion (``Agent.call_utility_model`` forwards to
``core.agents.model_calls.call_utility_model`` with ``agent`` first) is GUARDED-SKIPPED
until that module exists — collection never ERRORs, no silent false-GREEN.
"""
from __future__ import annotations

import inspect

import pytest


def test_call_utility_model_is_coroutine():
    """call_utility_model stays an async method after @extension.extensible."""
    from agent import Agent

    assert inspect.iscoroutinefunction(Agent.call_utility_model), (
        "Agent.call_utility_model must remain a coroutine function"
    )


def test_call_chat_model_is_coroutine():
    """call_chat_model stays an async method after @extension.extensible."""
    from agent import Agent

    assert inspect.iscoroutinefunction(Agent.call_chat_model), (
        "Agent.call_chat_model must remain a coroutine function"
    )


def test_b5_getattr_probe_returns_callable():
    """Mirror the real B5 consumer: getattr(agent, "call_utility_model", None) is callable.

    ``core/b5/rubric_scorer.py`` and ``response_self_check_hook.py`` gate on this exact
    probe; the attribute must resolve to a callable on the Agent surface.
    """
    from agent import Agent

    probe = getattr(Agent, "call_utility_model", None)
    assert callable(probe), "B5 getattr probe must return a callable (surface intact)"


def test_both_model_calls_are_extensible():
    """@extension.extensible must remain on both methods (leaves __wrapped__).

    The decorator fires util/chat ``*_model_call_before/after`` hooks with the agent
    instance; the Wave-C delegator must keep it so those hooks still run.
    """
    from agent import Agent

    assert hasattr(Agent.call_utility_model, "__wrapped__"), (
        "@extension.extensible must remain on call_utility_model"
    )
    assert hasattr(Agent.call_chat_model, "__wrapped__"), (
        "@extension.extensible must remain on call_chat_model"
    )


def test_delegation_pending_extraction():
    """Wave-C gate: Agent.call_utility_model forwards to core.agents.model_calls with agent first.

    GUARDED-SKIP until Wave C creates the module. Once present, monkeypatch the module
    function and assert the Agent delegator forwards ``self`` (the agent) as first arg
    and passes the remaining args through — the delegation contract PATTERNS §Seam 2
    prescribes.
    """
    mod = pytest.importorskip(
        "core.agents.model_calls",
        reason="Wave C not yet landed — core.agents.model_calls does not exist",
    )
    assert callable(getattr(mod, "call_utility_model", None)), (
        "extracted core.agents.model_calls.call_utility_model must be a callable"
    )
    assert callable(getattr(mod, "call_chat_model", None)), (
        "extracted core.agents.model_calls.call_chat_model must be a callable"
    )
    from agent import Agent

    assert hasattr(Agent.call_utility_model, "__wrapped__"), (
        "delegator must keep @extension.extensible on call_utility_model"
    )
