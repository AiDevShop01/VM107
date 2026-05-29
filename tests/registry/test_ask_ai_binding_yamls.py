"""Phase 71 Wave 2 — GREEN tests for `ask_ai_binding` registry YAMLs.

Plan 03 Task 2 ships the 7 `ask_ai_binding` YAML entries under
`VM107/registry/ask_ai_binding/`. These are the per-surface AskAI button
bindings consumed by `VM100/frontend/lib/ai/surface-bindings.js` (Plan 05).

Schema per CONTEXT Decision 5 and the Plan 01 `AskAISurfaceBinding`
Pydantic contract (fingpt_core.contracts.ask_ai_binding):
- route: frontend pathname (must be non-empty)
- conversation_type: must be in CONVERSATION_TYPES
- context_provider: VM107 tool ID that hydrates context
- allowed_tools: list[str]
- required_capability: str | None  (RBAC gate)

Required routes per CONTEXT Decision 5:
- /mission-control/opportunities/:id  (pre_trade OR execution_chat)
- /mission-control/positions/:id      (execution_chat)
- /mission-control/attention/:id      (macro_chat OR research_chat)
- /trading/replay/:trade_id           (reflection_chat)
- /research-lab/strategies/:id        (strategy_chat)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import yaml

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

os.environ.setdefault("CHAT_MODEL", "test-model")

CANONICAL_CONVERSATION_TYPES = {
    "pre_trade",
    "macro_chat",
    "execution_chat",
    "reflection_chat",
    "research_chat",
    "strategy_chat",
}

REQUIRED_ROUTES = {
    "/mission-control/opportunities/:id",
    "/mission-control/positions/:id",
    "/mission-control/attention/:id",
    "/trading/replay/:trade_id",
    "/research-lab/strategies/:id",
}


def _binding_dir() -> Path:
    return _VM107_ROOT / "registry" / "ask_ai_binding"


def _load_all_bindings() -> list[dict]:
    return [
        yaml.safe_load(p.read_text()) for p in sorted(_binding_dir().glob("*.yaml"))
    ]


def test_binding_dir_exists():
    assert _binding_dir().exists(), f"Plan 03 must create directory {_binding_dir()}"


def test_at_least_7_bindings():
    bindings = _load_all_bindings()
    assert len(bindings) >= 7, (
        f"Expected >=7 ask_ai_binding YAMLs, got {len(bindings)}"
    )


def test_all_required_routes_covered():
    bindings = _load_all_bindings()
    routes = {b["route"] for b in bindings}
    missing = REQUIRED_ROUTES - routes
    assert not missing, f"Missing required routes: {missing}"


def test_all_conversation_types_canonical():
    bindings = _load_all_bindings()
    bad = [b["id"] for b in bindings if b["conversation_type"] not in CANONICAL_CONVERSATION_TYPES]
    assert not bad, (
        f"Bindings with non-canonical conversation_type: {bad}. "
        f"Canonical set: {sorted(CANONICAL_CONVERSATION_TYPES)}"
    )


@pytest.mark.parametrize("binding_path", sorted(_binding_dir().glob("*.yaml")) if _binding_dir().exists() else [])
def test_each_binding_carries_required_fields(binding_path):
    data = yaml.safe_load(Path(binding_path).read_text())
    for field in ("id", "type", "status", "route", "conversation_type", "context_provider", "allowed_tools"):
        assert field in data, f"{binding_path.name}: missing field {field!r}"
    assert data["type"] == "ask_ai_binding"
    assert data["status"] in ("real", "planned", "deprecated", "stub", "experimental")
    assert isinstance(data["route"], str) and len(data["route"]) > 0
    assert isinstance(data["allowed_tools"], list)


def test_binding_passes_8_stage_validator():
    """All ask_ai_binding YAMLs pass the 8-stage capability registry validator
    (Stage 7 Rule 5 enforces conversation_type -> conversation_mode cross-ref).
    """
    from core.registry.capability_registry import CapabilityRegistry  # type: ignore[import-not-found]

    CapabilityRegistry._instance = None
    try:
        reg = CapabilityRegistry.initialize(_VM107_ROOT / "registry")
        binding_ids = {
            e.id for e in reg.snapshot.entries if e.type.value == "ask_ai_binding"
        }
        assert len(binding_ids) >= 7, (
            f"Validator surfaced {len(binding_ids)} ask_ai_binding entries; "
            f"expected >=7. Got: {sorted(binding_ids)}"
        )
    finally:
        CapabilityRegistry._instance = None


def test_binding_via_pydantic_contract():
    """Each YAML's binding fields construct a valid AskAISurfaceBinding Pydantic model."""
    from fingpt_core.contracts.ask_ai_binding import AskAISurfaceBinding  # type: ignore[import-not-found]

    bindings = _load_all_bindings()
    for raw in bindings:
        model = AskAISurfaceBinding(
            route=raw["route"],
            conversation_type=raw["conversation_type"],
            context_provider=raw["context_provider"],
            allowed_tools=raw.get("allowed_tools", []),
            required_capability=raw.get("required_capability"),
        )
        assert model.route == raw["route"]
        assert model.conversation_type in CANONICAL_CONVERSATION_TYPES
