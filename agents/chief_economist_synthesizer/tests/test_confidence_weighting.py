"""Phase 94 Wave 0 — Chief Economist Synthesizer confidence weighting RED scaffold.

Becomes GREEN in 94-06.
"""

from __future__ import annotations

import importlib

import pytest


def _require_synthesizer():
    try:
        return importlib.import_module("agents.chief_economist_synthesizer.agent")
    except ImportError as exc:
        pytest.fail(
            "Wave 6 (94-06) must create agents/chief_economist_synthesizer/agent.py. "
            f"ImportError: {exc}"
        )


def test_synthesizer_uses_weighted_not_simple_average():
    _require_synthesizer()
    pytest.fail(
        "Wave 6 must combine specialist confidences via weighted average "
        "(weights from specialist authority / domain match), not simple mean."
    )
