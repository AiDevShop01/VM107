"""Phase 90 Plan 06 — macro_forecast_narrator agent tests (TDD RED/GREEN).

These tests enforce the LD-90-1 lock at the agent layer:

  - Narrator emits ExplanationResult (NOT ForecastResult). The two envelope
    types accept disjoint `producer_kind` values — ForecastResult rejects
    `producer_kind="llm"` via @model_validator(mode='before') with an
    `LD-90-1` error string. So if the narrator's output ever round-tripped
    through ForecastResult.model_validate(...), Pydantic raises.

  - Hard assertion `narrator_no_value_prediction`: regex
    `\\b(will be|will reach|will print)\\b` MUST NOT match the narrative.
    Match -> retry ONCE with corrective addendum. If matched again, the
    envelope returns with b5_self_eval_passed=False (degraded).

  - Hard assertion `narrative_cites_evidence`: at least one
    `[ref:(episode|release):<ID>]` citation MUST appear. Missing -> degraded
    (b5_self_eval_passed=False) but still returned.

  - Capability Registry YAML loads cleanly under the boot-validation sweep
    (type: agent_profile, status: real, shipped: 90).

The forecast_result_stub fixture is provided by tests/phase90/conftest.py
(canonical Phase 90 envelope shape). The b5_stub fixture also lives there
but is not required for these tests — Plan 06 chooses regex-driven hard
assertions over the heavier Brain-B5 dispatch wiring (the YAML lists the
assertions; the agent enforces them directly).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

pytestmark = pytest.mark.phase90


# ---------------------------------------------------------------------------
# 1. ExplanationResult-not-ForecastResult lock
# ---------------------------------------------------------------------------

def _build_forecast_input(stub: dict) -> dict:
    """Make a Plan-2-style ForecastResult-shaped dict for the narrator."""
    return dict(stub)


def test_narrator_returns_explanation_result_not_forecast_result(forecast_result_stub):
    """Narrator output is an ExplanationResult — never a ForecastResult.

    The narrator emits text via LLM. We patch ``call_llm`` to return a
    citation-bearing narrative so all assertions pass. The returned object
    MUST be an ExplanationResult instance.
    """
    from fingpt_core.contracts.explanation_result import ExplanationResult
    from agents.macro_forecast_narrator.agent import macro_forecast_narrator_agent

    narrative = (
        "The model expects upward pressure on CPI over the 3-month horizon "
        "given recent oil moves [ref:release:CPIAUCSL-2026-03]."
    )
    with patch("agents.macro_forecast_narrator.agent.call_llm", return_value=narrative):
        result = asyncio.run(
            macro_forecast_narrator_agent(_build_forecast_input(forecast_result_stub))
        )

    assert isinstance(result, ExplanationResult)
    assert result.indicator_id == forecast_result_stub["indicator_id"]
    assert result.producer_kind == "llm"
    assert result.b5_self_eval_passed is True
    assert len(result.phase71_citations) >= 1


def test_narrator_result_dump_rejected_by_forecast_result_validator(forecast_result_stub):
    """ExplanationResult cannot be coerced into ForecastResult (LD-90-1 lock).

    Round-trip the narrator's ExplanationResult through
    ForecastResult.model_validate(...) — Pydantic MUST raise with
    `LD-90-1` in the error string (the @model_validator(mode='before')
    on ForecastResult intercepts producer_kind='llm').
    """
    from pydantic import ValidationError
    from fingpt_core.contracts.forecast_result import ForecastResult
    from agents.macro_forecast_narrator.agent import macro_forecast_narrator_agent

    narrative = (
        "The model indicates upward pressure on CPI "
        "[ref:release:CPIAUCSL-2026-03]."
    )
    with patch("agents.macro_forecast_narrator.agent.call_llm", return_value=narrative):
        result = asyncio.run(
            macro_forecast_narrator_agent(_build_forecast_input(forecast_result_stub))
        )

    payload = result.model_dump(mode="json")
    with pytest.raises(ValidationError) as exc:
        ForecastResult.model_validate(payload)
    assert "LD-90-1" in str(exc.value)


# ---------------------------------------------------------------------------
# 2. Hard assertion: narrator_no_value_prediction
# ---------------------------------------------------------------------------

def test_value_prediction_will_be_triggers_retry_then_degrade(forecast_result_stub):
    """Narrative containing "will be" triggers ONE retry with corrective addendum.

    If the retried narrative ALSO contains a value-prediction phrase,
    the result is returned with b5_self_eval_passed=False (degraded).
    The agent does NOT raise.
    """
    from agents.macro_forecast_narrator.agent import macro_forecast_narrator_agent

    bad = "CPI will be 3.4% next month [ref:release:CPIAUCSL-2026-03]."
    worse = "It will reach 3.4 [ref:release:CPIAUCSL-2026-03]."
    call_log: list[str] = []

    def fake_llm(prompt: str) -> str:
        call_log.append(prompt)
        return bad if len(call_log) == 1 else worse

    with patch("agents.macro_forecast_narrator.agent.call_llm", side_effect=fake_llm):
        result = asyncio.run(
            macro_forecast_narrator_agent(_build_forecast_input(forecast_result_stub))
        )

    assert len(call_log) == 2, "Narrator must retry exactly once on value-prediction"
    assert result.b5_self_eval_passed is False
    # The corrective addendum must mention LD-90-1 / value-prediction explicitly.
    assert "CORRECTION" in call_log[1] or "value prediction" in call_log[1].lower()


def test_value_prediction_clean_retry_passes(forecast_result_stub):
    """First emit contains 'will reach' — retry succeeds — b5_self_eval_passed=True."""
    from agents.macro_forecast_narrator.agent import macro_forecast_narrator_agent

    bad = "Inflation will reach 3.4 percent [ref:release:CPIAUCSL-2026-03]."
    good = (
        "The model expects upward pressure on CPI over the 3-month horizon "
        "[ref:release:CPIAUCSL-2026-03]."
    )
    call_log: list[str] = []

    def fake_llm(prompt: str) -> str:
        call_log.append(prompt)
        return bad if len(call_log) == 1 else good

    with patch("agents.macro_forecast_narrator.agent.call_llm", side_effect=fake_llm):
        result = asyncio.run(
            macro_forecast_narrator_agent(_build_forecast_input(forecast_result_stub))
        )

    assert len(call_log) == 2
    assert result.b5_self_eval_passed is True
    assert "will reach" not in result.explanation_text
    assert "will be" not in result.explanation_text


def test_value_prediction_assertion_passes_clean_narrative(forecast_result_stub):
    """Narrative free of value-prediction phrases passes on first attempt."""
    from agents.macro_forecast_narrator.agent import macro_forecast_narrator_agent

    clean = (
        "The model expects upward pressure on CPI over the 3-month horizon "
        "given recent oil moves [ref:release:CPIAUCSL-2026-03]."
    )
    call_log: list[str] = []

    def fake_llm(prompt: str) -> str:
        call_log.append(prompt)
        return clean

    with patch("agents.macro_forecast_narrator.agent.call_llm", side_effect=fake_llm):
        result = asyncio.run(
            macro_forecast_narrator_agent(_build_forecast_input(forecast_result_stub))
        )

    assert len(call_log) == 1, "Clean narrative should not trigger a retry"
    assert result.b5_self_eval_passed is True


# ---------------------------------------------------------------------------
# 3. Hard assertion: narrative_cites_evidence
# ---------------------------------------------------------------------------

def test_missing_citation_marks_envelope_degraded(forecast_result_stub):
    """Narrative with no [ref:...] citation -> b5_self_eval_passed=False.

    The envelope is still returned (so Phase 85 §11 widget can decide what
    to do); it is just flagged as degraded.
    """
    from agents.macro_forecast_narrator.agent import macro_forecast_narrator_agent

    uncited = "The model expects upward pressure on CPI over the next quarter."
    with patch("agents.macro_forecast_narrator.agent.call_llm", return_value=uncited):
        result = asyncio.run(
            macro_forecast_narrator_agent(_build_forecast_input(forecast_result_stub))
        )

    assert result.b5_self_eval_passed is False
    assert result.phase71_citations == []


def test_citation_extracted_from_narrative(forecast_result_stub):
    """phase71_citations list is populated from [ref:...] occurrences in the narrative."""
    from agents.macro_forecast_narrator.agent import macro_forecast_narrator_agent

    narrative = (
        "The model expects upward CPI pressure "
        "[ref:release:CPIAUCSL-2026-03] consistent with the 1973 episode "
        "[ref:episode:cpi-shock-1973]."
    )
    with patch("agents.macro_forecast_narrator.agent.call_llm", return_value=narrative):
        result = asyncio.run(
            macro_forecast_narrator_agent(_build_forecast_input(forecast_result_stub))
        )

    assert result.b5_self_eval_passed is True
    assert "release:CPIAUCSL-2026-03" in " ".join(result.phase71_citations)
    assert "episode:cpi-shock-1973" in " ".join(result.phase71_citations)


# ---------------------------------------------------------------------------
# 4. Capability Registry YAML loads under boot-validation sweep
# ---------------------------------------------------------------------------

YAML_PATH = (
    Path(__file__).resolve().parents[2]
    / "registry"
    / "agent_profile"
    / "vm107.macro_forecast_narrator.yaml"
)


def test_capability_registry_yaml_loads_and_validates():
    """vm107.macro_forecast_narrator.yaml exists, parses, and has required fields.

    Boot-validation sweep checks: id, type=agent_profile, status, shipped,
    allowed_tools, hard_assertions. The denied_tools list MUST include
    belief_store.propose (LD-90-1 + Phase 87 DETERMINISTIC_PROPOSERS lock).
    """
    assert YAML_PATH.exists(), f"missing Capability Registry YAML: {YAML_PATH}"
    data = yaml.safe_load(YAML_PATH.read_text(encoding="utf-8"))

    assert data["id"] == "vm107.macro_forecast_narrator"
    assert data["type"] == "agent_profile"
    assert data["status"] == "real"
    assert data["shipped"] == 90
    assert data["capability_type"] == "agent"
    assert data["vm"] == "vm107"

    allowed = data["allowed_tools"]
    assert "vm102_forecast_indicator" in allowed
    assert "vm102_forecast_regime" in allowed

    denied = data["denied_tools"]
    assert "belief_store.propose" in denied, (
        "LD-90-1 + Phase 87 lock: narrator must not propose beliefs"
    )

    hard_assertions = data["hard_assertions"]
    assertion_ids = {h["id"] for h in hard_assertions}
    assert "narrator_no_value_prediction" in assertion_ids
    assert "narrative_cites_evidence" in assertion_ids


def test_narrator_yaml_is_in_agent_profile_directory_not_agents():
    """Plan 06 lock: the YAML lives under registry/agent_profile/ (NOT agents/).

    Phase 87 exemplar (vm107.macro_regime_analyst.yaml) and the Plan 05
    sibling (vm107.macro_surprise_forecaster.yaml) both live there.
    A stray copy under registry/agents/ would split the registry sweep.
    """
    wrong_path = (
        Path(__file__).resolve().parents[2]
        / "registry"
        / "agents"
        / "vm107.macro_forecast_narrator.yaml"
    )
    assert YAML_PATH.exists()
    assert not wrong_path.exists(), (
        "Narrator YAML must live in registry/agent_profile/, not registry/agents/"
    )
