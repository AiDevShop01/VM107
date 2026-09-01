"""Phase 173 (D-05) — MacroContradictionDetector thin-agent binding tests.

Asserts the thin agent surface over the built core/contradiction/ContradictionEngine:
  1. Constructing MacroContradictionDetector(engine=<fake>) needs NO
     CONTRADICTION_POSTGRES_URL (no live psycopg2 connect at import/construct).
  2. emit_for_release(release_event) delegates to the injected engine's
     detect_divergence → grade_severity → write_contradiction (release-derived
     args), and recomputes NO detection math in the agent.
  3. The module dir agents/macro_contradiction_detector/ is importable
     (dispatch reachability by dir presence).
  4. The return value is a stats dict echoing indicator_id + severity + emitted
     count (mirror the emitter return shape).

Uses a fake/mock engine injected via the DI ctor — the real ContradictionEngine
is NEVER constructed here (no live Postgres). Marked ``quick``; NOT
``requires_deps``.
"""
from __future__ import annotations

import importlib
import inspect
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.quick

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


# ── Fake engine double ────────────────────────────────────────────────────────


class _FakeSeverityResult:
    """Stand-in for core.contradiction.severity_grader.SeverityResult."""

    def __init__(self, severity: str = "warning") -> None:
        self.severity = severity
        self.triggers_fired: list[str] = ["single_asset_warning"]
        self.ui_surface = "indicator_page_banner"
        self.downstream_confidence_delta = -0.20


class _FakeEngine:
    """Records calls so the agent's delegation to the built engine is asserted.

    Exposes the ContradictionEngine public surface the thin agent binds:
    detect_divergence / grade_severity / active_blocking / write_contradiction.
    """

    def __init__(self, *, severity: str = "warning") -> None:
        self._severity = severity
        self.calls: dict[str, object] = {}

    def detect_divergence(self, indicator_id, predicted_per_asset, actual_per_asset, sigma_historical):
        self.calls["detect_divergence"] = {
            "indicator_id": indicator_id,
            "predicted_per_asset": predicted_per_asset,
            "actual_per_asset": actual_per_asset,
            "sigma_historical": sigma_historical,
        }
        # Return a canned per-asset sigma — the AGENT must NOT recompute this.
        return {"DXY": 3.0}

    def grade_severity(self, divergence_sigma_per_asset, active_beliefs):
        self.calls["grade_severity"] = {
            "divergence_sigma_per_asset": divergence_sigma_per_asset,
            "active_beliefs": active_beliefs,
        }
        return _FakeSeverityResult(severity=self._severity)

    def active_blocking(self, indicator_id):
        return False

    def write_contradiction(self, artifact):
        self.calls["write_contradiction"] = {"artifact": artifact}

    def close(self):
        self.calls["close"] = True


def _release_event() -> dict:
    return {
        "indicator_id": "CPIAUCSL",
        "release_date": "2026-06-25",
        "predicted_per_asset": {"DXY": 0.8},
        "actual_per_asset": {"DXY": 1.4},
        "sigma_historical": {"DXY": 1.0},
        "active_beliefs": [],
    }


# ── Test 1: construct with injected fake engine — no live Postgres ────────────


def test_construct_with_injected_engine_needs_no_postgres_url():
    from agents.macro_contradiction_detector.agent import MacroContradictionDetector

    # Prove no CONTRADICTION_POSTGRES_URL is required at construct time.
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("CONTRADICTION_POSTGRES_URL", None)
        detector = MacroContradictionDetector(engine=_FakeEngine())

    assert detector.agent_id == "vm107.macro_contradiction_detector"


# ── Test 2: delegates to the engine; recomputes no detection math ─────────────


def test_emit_for_release_delegates_to_engine():
    from agents.macro_contradiction_detector import agent as agent_mod
    from agents.macro_contradiction_detector.agent import MacroContradictionDetector

    fake = _FakeEngine(severity="warning")
    event = _release_event()

    with patch.object(agent_mod, "emit_alert_candidate") as mock_emit:
        MacroContradictionDetector(engine=fake).emit_for_release(event)

    # detect_divergence received the release-derived args verbatim.
    dd = fake.calls["detect_divergence"]
    assert dd["indicator_id"] == "CPIAUCSL"
    assert dd["predicted_per_asset"] == {"DXY": 0.8}
    assert dd["actual_per_asset"] == {"DXY": 1.4}
    assert dd["sigma_historical"] == {"DXY": 1.0}

    # grade_severity received the divergence the ENGINE returned (not a recompute).
    gs = fake.calls["grade_severity"]
    assert gs["divergence_sigma_per_asset"] == {"DXY": 3.0}

    # write_contradiction was called with a persisted artifact carrying the id + engine grade.
    art = fake.calls["write_contradiction"]["artifact"]
    assert art.indicator_id == "CPIAUCSL"
    assert art.severity == "warning"
    assert art.divergence_sigma == {"DXY": 3.0}

    # warning/blocking → an alert candidate is emitted via the shared phase91 shim.
    assert mock_emit.call_count == 1

    # Static guard — the agent must NOT reimplement the divergence formula.
    src = inspect.getsource(agent_mod)
    assert "sigma_historical" not in src or "/ sigma" not in src
    for banned in ("def detect_divergence", "def grade_severity", "abs(actual"):
        assert banned not in src, f"agent reimplements engine math: {banned!r}"


# ── Test 3: module dir importable — dispatch reachability by dir presence ──────


def test_module_dir_is_importable():
    mod = importlib.import_module("agents.macro_contradiction_detector.agent")
    assert hasattr(mod, "MacroContradictionDetector")
    assert hasattr(mod, "emit_for_release")


# ── Test 4: return is a stats dict echoing indicator_id + severity + count ─────


def test_emit_for_release_returns_stats_dict():
    from agents.macro_contradiction_detector import agent as agent_mod
    from agents.macro_contradiction_detector.agent import MacroContradictionDetector

    fake = _FakeEngine(severity="warning")
    with patch.object(agent_mod, "emit_alert_candidate"):
        result = MacroContradictionDetector(engine=fake).emit_for_release(_release_event())

    assert result["indicator_id"] == "CPIAUCSL"
    assert result["severity"] == "warning"
    assert result["emitted_count"] == 1


def test_missing_indicator_id_is_honest_noop():
    from agents.macro_contradiction_detector.agent import MacroContradictionDetector

    result = MacroContradictionDetector(engine=_FakeEngine()).emit_for_release({})
    assert result["indicator_id"] is None
    assert result["emitted_count"] == 0
    assert result["skipped_no_indicator"] is True


# ── Test 6 (CR-01): the shim closes the engine it owns on every path ──────────


def test_shim_closes_owned_engine_on_success_and_exception():
    """The module-level shim lazily builds an engine it OWNS, so it must release
    the per-call Postgres connection on both the success and exception paths
    (CR-01 — else one connection leaks per event on the long-running process)."""
    from agents.macro_contradiction_detector import agent as agent_mod

    # ── Success path ──────────────────────────────────────────────────────────
    ok_engine = _FakeEngine(severity="warning")
    with patch.object(agent_mod, "ContradictionEngine", return_value=ok_engine), \
         patch.object(agent_mod, "emit_alert_candidate"):
        agent_mod.emit_for_release(_release_event())
    # The shim released the lazily-constructed engine's connection.
    assert ok_engine.calls.get("close") is True

    # ── Exception path ────────────────────────────────────────────────────────
    boom_engine = _FakeEngine(severity="warning")

    def _raise(_artifact):
        raise RuntimeError("write blew up")

    boom_engine.write_contradiction = _raise  # type: ignore[assignment]
    with patch.object(agent_mod, "ContradictionEngine", return_value=boom_engine), \
         patch.object(agent_mod, "emit_alert_candidate"):
        with pytest.raises(RuntimeError, match="write blew up"):
            agent_mod.emit_for_release(_release_event())
    # try/finally still closed the connection despite the raised exception.
    assert boom_engine.calls.get("close") is True

    # A DI-injected engine (caller-owned) is NOT closed by the agent.
    from agents.macro_contradiction_detector.agent import MacroContradictionDetector

    injected = _FakeEngine(severity="info")
    MacroContradictionDetector(engine=injected).close()
    assert "close" not in injected.calls
