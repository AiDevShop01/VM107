"""Phase 170 Plan 03 Task 3 — engine-lock guard for the net-new critic + causal packages.

The specialized-critic panel (`core/agents/specialized_critic/`) and the causal
mechanism registry (`core/causal/`) are DETERMINISTIC by contract (D-02): no LLM
SDK import, no recompute of engine state. A static allowlist tuple is the exact
hole Pitfall 3 warns about — a file added later is invisible to the guard. So this
test `glob("*.py")`s BOTH package dirs (future files are covered automatically) and
asserts NONE of the banned engine/LLM needles appear in any file.

Mirrors `tests/agents/test_domain_base_engine_lock.py` (same `_BANNED` needle set),
retargeted from a hard-coded file tuple to a glob-over-package.
"""
from __future__ import annotations

from pathlib import Path

import pytest

# tests/agents/test_*.py -> tests/agents -> tests -> VM107
_VM107_ROOT = Path(__file__).resolve().parents[2]

# Glob BOTH net-new packages so future files are covered automatically (Pitfall 3).
_GUARDED_DIRS = (
    _VM107_ROOT / "core" / "agents" / "specialized_critic",
    _VM107_ROOT / "core" / "causal",
)


def _guarded_files() -> list[Path]:
    files: list[Path] = []
    for directory in _GUARDED_DIRS:
        assert directory.is_dir(), f"guarded package dir missing: {directory}"
        files.extend(sorted(directory.glob("*.py")))
    assert files, "engine-lock guard found no files to check — glob misconfigured"
    return files


# Same banned set as test_domain_base_engine_lock.py::test_base_file_is_engine_locked
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


@pytest.mark.parametrize("path", _guarded_files(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_critic_and_causal_files_are_engine_locked(path: Path):
    """No specialized_critic/ or causal/ file contains an engine-recompute or LLM import."""
    source = path.read_text()
    for needle in _BANNED:
        assert needle not in source, (
            f"banned symbol {needle!r} found in {path.relative_to(_VM107_ROOT)} — "
            f"the specialized-critic panel + causal registry are deterministic (D-02); "
            f"the engine-lock must not be hollowed out"
        )
