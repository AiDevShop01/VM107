"""Phase 169 Plan 02 Task 3 — base-file engine-lock guard.

The per-slug guard (`tests/agents/test_domain_analyst_contract.py::test_never_recomputes_score`)
reads only `agents/<slug>_domain_analyst/agent.py`. When the shared logic moves UP onto the
generic base (`core/agents/domain_agent.py`, Plan 169-02), that grep never reads the base —
so an engine recompute or an LLM import could be smuggled behind it (Pitfall 1c).

This test closes the hole: it `read_text()`s BOTH base files
(`core/agents/domain_agent.py` and `core/agents/domain_definition.py`) and asserts NONE of
the banned engine/LLM needles appear. The needle list mirrors the per-slug guard verbatim.
"""
from __future__ import annotations

from pathlib import Path

import pytest

# VM107 root: tests/agents/test_*.py -> tests/agents -> tests -> VM107
_VM107_ROOT = Path(__file__).resolve().parent.parent.parent

_BASE_FILES = (
    _VM107_ROOT / "core" / "agents" / "domain_agent.py",
    _VM107_ROOT / "core" / "agents" / "domain_definition.py",
)

# Same banned set as test_domain_analyst_contract.py::test_never_recomputes_score
# (engine recompute modules + LLM SDK imports — Phase 94 §F.3 + LD-90-1).
_BANNED = (
    "level_engine",
    "momentum_engine",
    "breadth_engine",
    "compute_pillar",
    "compute_domain",
    "compute_level",
    "compute_momentum",
    "compute_breadth",
    "import openai",
    "import anthropic",
    "import litellm",
    "from openai",
    "from anthropic",
    "from litellm",
)


@pytest.mark.parametrize("path", _BASE_FILES, ids=lambda p: p.name)
def test_base_file_is_engine_locked(path: Path):
    """The DomainAgent base + DomainDefinition loader contain no engine/LLM symbols."""
    assert path.exists(), f"base file missing: {path}"
    source = path.read_text()
    for needle in _BANNED:
        assert needle not in source, (
            f"banned symbol {needle!r} found in {path.relative_to(_VM107_ROOT)} — "
            f"the engine-lock must not be hollowed out by moving logic onto the base"
        )
