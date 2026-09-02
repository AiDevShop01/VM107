"""Phase 172 Plan 01 Task 2 — SC-6 runtime-wiring orphan guard.

The whole point of Phase 172 is that the v6.5 evidence/assessment/critic substrate
(``assemble()`` / ``assess()`` / ``run_panel()``) was BUILT and densely unit-tested
but has **zero production call-sites** — it is orphaned. A green unit suite hides
that: every one of these callables is exercised only from ``tests/``.

This guard is the permanent anti-orphan regression. Mirroring the established
``test_domain_base_engine_lock.py`` ``read_text()`` needle-scan pattern (but with the
assertion INVERTED — presence, not absence), it aggregates the NON-test source under
``core/`` + ``agents/`` and asserts each callable has **>=1 call-site** in production
code. The defining module for each needle is excluded so the ``def`` itself never
counts as its own caller.

State transition (by design):
  * RED at plan time — SC-1/SC-2 have not yet wired the subscriber call-sites, so
    every needle is absent from non-test code and this guard FAILS. That RED is the
    proof the guard actually gates the orphan state.
  * GREEN once 172-04 (SC-1: ``assemble`` + ``assess``) and 172-05 (SC-2 D-02a:
    ``run_panel``) land their call-sites inside
    ``agents/domain_analyst_subscriber/subscriber.py``.
  * RED again if a future refactor silently re-orphans any callable — turning the
    phase gate red instead of letting the regression pass unnoticed.

Host-clean: pure stdlib (``pathlib``) source-text scan; imports no production module.
"""
from __future__ import annotations

from pathlib import Path

import pytest

# VM107 root: tests/agents/test_*.py -> tests/agents -> tests -> VM107
_VM107_ROOT = Path(__file__).resolve().parent.parent.parent

# The production trees a live call-site is allowed to live in (SC-6: core/ + agents/).
_SCAN_ROOTS = ("core", "agents")


class _NeedleSpec:
    """One orphan-guard target: the call needle + the module that DEFINES it."""

    def __init__(self, needle: str, callable_name: str, defining_module: Path) -> None:
        self.needle = needle
        self.callable_name = callable_name
        self.defining_module = defining_module

    def __repr__(self) -> str:  # pragma: no cover - id helper only
        return self.callable_name


# The three orphaned callables + the module each is DEFINED in (excluded from the
# scan so the ``def`` never counts as its own caller).
_NEEDLES = (
    _NeedleSpec(
        needle="assemble(",
        callable_name="assemble",
        defining_module=_VM107_ROOT / "core" / "evidence" / "assembler.py",
    ),
    _NeedleSpec(
        # Dotted call form (``agent.assess(...)`` / ``self.assess(...)``) so the
        # bare ``def assess(`` definition never matches.
        needle=".assess(",
        callable_name="assess",
        defining_module=_VM107_ROOT / "core" / "agents" / "domain_agent.py",
    ),
    _NeedleSpec(
        needle="run_panel(",
        callable_name="run_panel",
        defining_module=_VM107_ROOT / "core" / "agents" / "specialized_critic" / "panel.py",
    ),
)


def _non_test_sources(exclude: Path) -> list[Path]:
    """Every ``*.py`` under the scan roots, minus tests and the defining module."""
    exclude = exclude.resolve()
    out: list[Path] = []
    for root_name in _SCAN_ROOTS:
        root = _VM107_ROOT / root_name
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            # Exclude anything living under a ``tests`` segment — the substrate is
            # only ever called from tests today; that is exactly the orphan state.
            if "tests" in path.parts:
                continue
            if path.resolve() == exclude:
                continue
            out.append(path)
    return out


@pytest.mark.parametrize("spec", _NEEDLES, ids=lambda s: s.callable_name)
def test_callable_has_non_test_caller(spec: _NeedleSpec):
    """SC-6: ``assemble()`` / ``assess()`` / ``run_panel()`` each need >=1 live caller.

    Fails (RED) while the callable is orphaned — i.e. has no call-site outside
    ``tests/`` — proving the substrate is not wired into the live MACRO_RELEASE path.
    """
    assert spec.defining_module.exists(), (
        f"defining module missing for {spec.callable_name}: {spec.defining_module}"
    )

    callers: list[str] = []
    for path in _non_test_sources(exclude=spec.defining_module):
        try:
            source = path.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        if spec.needle in source:
            callers.append(str(path.relative_to(_VM107_ROOT)))

    assert callers, (
        f"SC-6 ORPHAN: `{spec.callable_name}()` has NO non-test caller — the "
        f"needle {spec.needle!r} appears nowhere under core/ + agents/ (excluding "
        f"tests/ and its defining module {spec.defining_module.relative_to(_VM107_ROOT)}). "
        f"The v6.5 substrate is re-orphaned: it is built + unit-tested but never "
        f"reached on the live MACRO_RELEASE path. Wire a production call-site "
        f"(SC-1 for assemble/assess, SC-2 D-02a for run_panel) in "
        f"agents/domain_analyst_subscriber/subscriber.py."
    )
