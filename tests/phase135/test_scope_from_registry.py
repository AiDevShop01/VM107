"""Phase 135 D5 — tool-scope-from-registry regression lock (D5-01, NO behavior change).

Locks the existing, authoritative behavior ([[project_vm107_agent_tool_scope]]): the
tool-authorization decision is read from `CapabilityRegistry`, never from an agent's
natural-language self-report. This is a TEST-ONLY artifact — per D5-01/D5-02 it adds NO
runtime assert/guard on the fragile dispatch hot path and NO observability log line.

What is locked:
  1. `CapabilityRegistry.is_capability_in_scope(profile, capability_id)` is the decision
     authority: a listed (profile, hard-tool) pair -> True; an unlisted profile -> False.
  2. The dispatch route `check_tool_scope -> is_tool_allowed -> is_capability_in_scope`
     denies an unlisted profile with `UnauthorizedToolError`, and provably consults
     `is_capability_in_scope` to make that decision (spied).
  3. The scope decision for a FIXED (profile, capability_id) is invariant to any
     message / NL content — proven by the ABSENCE of any message/claim/content parameter
     on the entire authorization call chain. There is no code path that accepts an agent
     self-report, so no self-report can change the decision. This test guards that absence.

Analogs: tests/registry/test_loader.py::test_is_capability_in_scope (assertion shape),
tests/agents/test_tool_scope_parity.py (real-registry init + keyword-arg call shape),
tests/phase89/test_capability_registry_sweep.py (phaseNNN structure).
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

# Repo root on sys.path so `core.*` imports under the container venv (mirrors phase134/parity).
_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

# A hard-scoped tool with a known allow-list in the live registry (verified 2026-08-05):
#   agent_zero  IS allowed to use code_execution_tool  -> in-scope / no raise
#   idea_agent  is NOT allowed to use code_execution_tool -> out-of-scope / raises
HARD_TOOL = "code_execution_tool"
LISTED_PROFILE = "agent_zero"
UNLISTED_PROFILE = "idea_agent"


@pytest.fixture(autouse=True)
def registry_initialized():
    """Initialize CapabilityRegistry against the REAL registry for every test, then restore.

    `check_tool_scope` -> `is_tool_allowed` calls `CapabilityRegistry.get()`, which raises
    (and `is_tool_allowed` falls back to permissive `True`) unless the singleton is set.
    Mirrors tests/agents/test_tool_scope_parity.py::registry_initialized.
    """
    from core.registry.capability_registry import CapabilityRegistry

    original_instance = CapabilityRegistry._instance
    CapabilityRegistry.initialize(_VM107_ROOT / "registry")
    yield
    CapabilityRegistry._instance = original_instance


# ── 1. The registry is the decision authority ────────────────────────────────


def test_listed_pair_in_scope():
    """A listed (profile, hard-tool) pair is in scope (is True)."""
    from core.registry.capability_registry import CapabilityRegistry

    reg = CapabilityRegistry.get()
    assert reg.is_capability_in_scope(profile=LISTED_PROFILE, capability_id=HARD_TOOL) is True


def test_unlisted_pair_out_of_scope():
    """An unlisted profile is out of scope for the hard tool (is False)."""
    from core.registry.capability_registry import CapabilityRegistry

    reg = CapabilityRegistry.get()
    assert reg.is_capability_in_scope(profile=UNLISTED_PROFILE, capability_id=HARD_TOOL) is False


# ── 2. The dispatch route denies via the registry ────────────────────────────


def test_denied_pair_raises_unauthorized():
    """`check_tool_scope` raises `UnauthorizedToolError` for an unlisted (profile, hard-tool)."""
    from core.agents.tool_scope import UnauthorizedToolError, check_tool_scope

    with pytest.raises(UnauthorizedToolError) as excinfo:
        check_tool_scope(UNLISTED_PROFILE, HARD_TOOL)
    assert excinfo.value.agent_id == UNLISTED_PROFILE
    assert excinfo.value.tool_name == HARD_TOOL


def test_allowed_pair_does_not_raise():
    """`check_tool_scope` does NOT raise for a listed (profile, hard-tool) — no behavior change."""
    from core.agents.tool_scope import check_tool_scope

    # Must not raise; a listed agent keeps its hard tool.
    check_tool_scope(LISTED_PROFILE, HARD_TOOL)


def test_dispatch_routes_through_capability_registry(monkeypatch):
    """The denial decision provably flows through `CapabilityRegistry.is_capability_in_scope`.

    Spies the registry method to record the exact (profile, capability_id) it was asked to
    judge, proving `check_tool_scope -> is_tool_allowed -> is_capability_in_scope` is the
    authoritative route (not any side channel).
    """
    from core.agents.tool_scope import UnauthorizedToolError, check_tool_scope
    from core.registry.capability_registry import CapabilityRegistry

    calls: list[tuple[str, str]] = []
    real = CapabilityRegistry.is_capability_in_scope

    def _spy(self, *args, **kwargs):
        profile = kwargs.get("profile", args[0] if args else None)
        capability_id = kwargs.get("capability_id", args[1] if len(args) > 1 else None)
        calls.append((profile, capability_id))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(CapabilityRegistry, "is_capability_in_scope", _spy)

    with pytest.raises(UnauthorizedToolError):
        check_tool_scope(UNLISTED_PROFILE, HARD_TOOL)

    assert (UNLISTED_PROFILE, HARD_TOOL) in calls, (
        "check_tool_scope must reach its verdict via CapabilityRegistry.is_capability_in_scope"
    )


# ── 3. The decision is invariant to any message / NL content ─────────────────


def test_scope_decision_has_no_nl_input_path():
    """The (profile, tool) scope decision is invariant to message/NL content.

    This is the T-135-05 guard: an agent's natural-language claim ("I have / lack tool X")
    must NEVER influence authorization. We prove it structurally — the ENTIRE authorization
    call chain accepts ONLY (profile/agent_id, tool/capability_id). No parameter named for
    a message, NL content, or agent claim exists on any hop, so there is no code path by
    which a self-report could reach the decision. If a future edit adds such a parameter,
    this test fails and forces a review.
    """
    from core.agents.tool_scope import check_tool_scope, is_tool_allowed
    from core.registry.capability_registry import CapabilityRegistry

    forbidden_param_substrings = ("message", "claim", "self_report", "selfreport", "content", "nl")

    for fn in (check_tool_scope, is_tool_allowed, CapabilityRegistry.is_capability_in_scope):
        params = [p for p in inspect.signature(fn).parameters if p != "self"]
        for name in params:
            lowered = name.lower()
            assert not any(sub in lowered for sub in forbidden_param_substrings), (
                f"{fn.__qualname__} exposes NL-shaped parameter {name!r}; scope must depend "
                f"ONLY on (profile, capability_id), never on agent self-report"
            )

    # And the decision itself is stable across repeated calls for a fixed pair (no hidden state).
    reg = CapabilityRegistry.get()
    first = reg.is_capability_in_scope(profile=UNLISTED_PROFILE, capability_id=HARD_TOOL)
    for _ in range(3):
        assert reg.is_capability_in_scope(profile=UNLISTED_PROFILE, capability_id=HARD_TOOL) is first
    assert first is False
