"""Phase 94 Wave 0 — macro_ask_router never-answers RED scaffold.

Becomes GREEN in 94-06.
"""

from __future__ import annotations

import importlib

import pytest


def _require_router():
    try:
        return importlib.import_module("agents.macro_ask_router.agent")
    except ImportError as exc:
        pytest.fail(
            "Wave 6 (94-06) must create agents/macro_ask_router/agent.py. "
            f"ImportError: {exc}"
        )


def test_router_never_returns_answer_field():
    _require_router()
    pytest.fail(
        "Wave 6 must ensure macro_ask_router.invoke() returns "
        "{required_agents, execution_order} — NEVER {answer}."
    )
