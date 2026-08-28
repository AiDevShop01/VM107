"""Phase 170 Plan 02 — tests/causal fixtures.

Reuses the Plan 01 shared SC#2 fixtures (`bare_correlation_assessment`,
`supported_assessment`) defined in the parent `tests/conftest.py` — they are
auto-discovered here, so this module only adds the registry-level fixtures the
mechanism-registry tests need on top of them (the real seeded registry + the
real profile dir it seeds from). No mocks — the registry is built from the real
169 `domain_definition:` blocks.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.causal.mechanism_registry import CausalMechanismRegistry
from core.causal.seed import build_registry

# tests/causal/conftest.py -> parents[2] == VM107 root
_VM107_ROOT = Path(__file__).resolve().parents[2]
_REAL_PROFILE_DIR = _VM107_ROOT / "registry" / "agent_profile"


@pytest.fixture
def real_profile_dir() -> Path:
    """The real shipped profile dir carrying the 12 domain_definition: blocks."""
    return _REAL_PROFILE_DIR


@pytest.fixture
def seeded_registry(real_profile_dir: Path) -> CausalMechanismRegistry:
    """The CausalMechanismRegistry seeded reuse-first from the real 169 blocks."""
    return build_registry(real_profile_dir)
