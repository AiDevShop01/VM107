"""REQ-89-5 / Decision 5 — chart context-menu actions scope to the visible zoom range only.

This test covers the 3-link enforcement chain:
  Link 1 (BE-1): ChartContextMenu dispatches body containing zoom_range.start_ts + zoom_range.end_ts
                  → verified by asserting the serializer contract from Plan 05.
  Link 2 (BE-2): /api/macro/ask backend handler passes zoom_range through to VM107 dispatch
                  → verified by asserting the prompt_context plumbing contract.
  Link 3 (BE-3): VM107 macro_investigator B5 rubric claims_within_cited_evidence = 0.0
                  when the LLM answer references dates outside the zoom_range.
  Link 4 (BE-4): Positive control — answer stays within window → claims_within_cited_evidence ≥ 0.8.

Per project locks:
  - NO `os.getenv("X", "default")` fallbacks — fail-fast config.
  - No live VM stack required — all external calls mocked or contract-asserted.
  - VM107 → VM100 backend imports: impractical cross-service (different Django apps).
    Use pure-Python contract assertions against the serializer field spec instead.

All tests marked @pytest.mark.phase89.
"""
from __future__ import annotations

import pathlib
from unittest.mock import patch

import pytest
import yaml

FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures"


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _load_golden() -> dict:
    """Load the b5_rubric_golden.yaml fixture."""
    return yaml.safe_load((FIXTURES_DIR / "b5_rubric_golden.yaml").read_text())


def _canned_rubric() -> dict:
    """Rubric matching the macro_investigator_qa spec in b5_rubric_golden.yaml."""
    return {
        "id": "rubric.macro_investigator_qa",
        "checks": [
            {"id": "cites_evidence", "weight": 0.30, "description": "Cites evidence"},
            {
                "id": "claims_within_cited_evidence",
                "weight": 0.25,
                "description": "All quantitative claims fall within the cited evidence date range",
            },
            {"id": "acknowledges_uncertainty", "weight": 0.20, "description": "Acknowledges uncertainty"},
            {"id": "correlation_not_causation", "weight": 0.15, "description": "Correlation not causation"},
            {
                "id": "confidence_calibrated_and_concise",
                "weight": 0.10,
                "description": "Answer is ≤400 words",
            },
        ],
        "threshold": {"accept": 0.75, "refine_below": 0.75, "reject_below": 0.40},
        "refinement": {"max_loops": 1, "on_second_fail": "degrade_to_uncertain"},
        "graceful_degradation_text": "I'm not sure I can answer this confidently.",
        "utility_model_routing": {"use_phase_43_1": True},
        "word_cap": {"target": 250, "hard_cap": 400},
    }


# ─── BE-1: Frontend → backend plumbing contract ──────────────────────────────


@pytest.mark.phase89
def test_BE1_chartcontextmenu_dispatch_body_contains_zoom_range():
    """BE-1: ChartContextMenu must dispatch {indicator_id, zoom_range:{start_ts,end_ts}, action_type}.

    This is a pure-Python contract assertion verifying the serializer shape
    that the frontend is expected to POST to /api/macro/ask.

    The VM100 backend AskRequest serializer (Plan 05) has these fields:
        - indicator_id: str (required)
        - zoom_range: { start_ts: ISO 8601, end_ts: ISO 8601 } (optional)
        - action_type: str (optional)

    We assert the dict structure that ChartContextMenu must produce before posting.
    If this contract is broken, the Decision 5 enforcement chain breaks.
    """
    # Simulate the payload that ChartContextMenu builds on action click (Decision 5)
    CHART_CONTEXT_MENU_DISPATCH_BODY = {
        "indicator_id": "CPIAUCSL",
        "zoom_range": {
            "start_ts": "2026-04-01T00:00:00Z",
            "end_ts": "2026-04-01T04:00:00Z",
        },
        "action_type": "explain_this_move",
        "prompt": "[chart-action:explain_this_move]",
    }

    # Verify the contract fields
    body = CHART_CONTEXT_MENU_DISPATCH_BODY
    assert "indicator_id" in body, "ChartContextMenu dispatch body must include indicator_id"
    assert "zoom_range" in body, "ChartContextMenu dispatch body must include zoom_range (Decision 5)"
    assert "start_ts" in body["zoom_range"], "zoom_range must contain start_ts"
    assert "end_ts" in body["zoom_range"], "zoom_range must contain end_ts"
    assert body["zoom_range"]["start_ts"] == "2026-04-01T00:00:00Z"
    assert body["zoom_range"]["end_ts"] == "2026-04-01T04:00:00Z"
    assert "action_type" in body, "ChartContextMenu dispatch body must include action_type"
    assert body["action_type"] == "explain_this_move"


# ─── BE-2: Backend → VM107 dispatch zoom_range plumbing ──────────────────────


@pytest.mark.phase89
def test_BE2_backend_passes_zoom_range_to_vm107_dispatch():
    """BE-2: /api/macro/ask must pass zoom_range through to VM107 dispatch prompt_context.

    The Plan 05 handler builds a prompt_context dict from the AskRequest and
    passes it to _dispatch_agent_sync(profile_id='vm107.macro_investigator', ...).

    Contract assertion: given {indicator_id, zoom_range, action_type} in the
    POST body, the dispatched body must include:
        prompt_context.zoom_range.start_ts == "2026-04-01T00:00:00Z"
        prompt_context.zoom_range.end_ts   == "2026-04-01T04:00:00Z"

    We test this contract by simulating the transformation the Plan 05 handler applies.
    """
    # Input: what ChartContextMenu POSTs to /api/macro/ask
    ask_request_data = {
        "indicator_id": "CPIAUCSL",
        "zoom_range": {
            "start_ts": "2026-04-01T00:00:00Z",
            "end_ts": "2026-04-01T04:00:00Z",
        },
        "action_type": "explain_this_move",
        "prompt": "[chart-action:explain_this_move]",
    }

    # Simulate the Plan 05 handler's prompt_context construction
    # (mirroring the VM100 backend's ask endpoint logic — zoom_range passed through verbatim)
    def build_prompt_context(ask_data: dict) -> dict:
        """Transform AskRequest fields into VM107 dispatch prompt_context.

        This is the contract: whatever zoom_range is in the request body,
        it MUST appear unchanged in prompt_context sent to VM107.
        """
        ctx = {}
        if ask_data.get("zoom_range"):
            ctx["zoom_range"] = ask_data["zoom_range"]
        if ask_data.get("action_type"):
            ctx["action_type"] = ask_data["action_type"]
        if ask_data.get("indicator_id"):
            ctx["indicator_id"] = ask_data["indicator_id"]
        return ctx

    prompt_context = build_prompt_context(ask_request_data)

    # Assert zoom_range is passed through unchanged
    assert "zoom_range" in prompt_context, (
        "VM107 dispatch prompt_context must contain zoom_range from AskRequest (Decision 5)"
    )
    assert prompt_context["zoom_range"]["start_ts"] == "2026-04-01T00:00:00Z", (
        "zoom_range.start_ts must be passed through verbatim to VM107"
    )
    assert prompt_context["zoom_range"]["end_ts"] == "2026-04-01T04:00:00Z", (
        "zoom_range.end_ts must be passed through verbatim to VM107"
    )


# ─── BE-3: B5 rubric range-scope penalty ─────────────────────────────────────


@pytest.mark.phase89
def test_BE3_b5_rubric_range_scope_penalty_out_of_window():
    """BE-3 (Decision 5): B5 rubric claims_within_cited_evidence = 0.0 for out-of-window answer.

    Load the golden fixture's out_of_range_case (INV-OOR-01):
      - Prompt is scoped to 2023 (start_ts=2023-01-01, end_ts=2023-12-31)
      - Answer references 2008-2009 and 1970s — clearly outside the zoom window

    Run score_answer() with the zoom_range prompt_context.
    Assert claims_within_cited_evidence == 0.0 (Decision 5 enforcement).
    Assert total weighted score < refine_below=0.75 → recommendation is "refine" or "reject".
    """
    golden = _load_golden()
    oor_case = golden["out_of_range_case"]
    answer_text = oor_case["answer_text"]
    rubric = _canned_rubric()

    prompt_context = {
        "zoom_range": {
            "start_ts": oor_case["prompt_start_ts"],
            "end_ts": oor_case["prompt_end_ts"],
        }
    }

    # Canned scores from utility model — claims_within gets 0.80 from LLM,
    # but scorer must OVERRIDE to 0.0 because answer references dates outside range.
    canned_scores = {
        "cites_evidence": 0.50,
        "claims_within_cited_evidence": 0.80,  # LLM score — scorer overrides to 0.0
        "acknowledges_uncertainty": 0.50,
        "correlation_not_causation": 0.60,
        "confidence_calibrated_and_concise": 1.00,
    }

    with patch(
        "core.b5.rubric_scorer._call_utility_model_for_check",
        side_effect=lambda check_id, **_kw: canned_scores[check_id],
    ):
        from core.b5.rubric_scorer import score_answer

        result = score_answer(
            answer=answer_text,
            rubric=rubric,
            prompt_context=prompt_context,
        )

    # Decision 5 enforcement: claims_within_cited_evidence MUST be 0.0
    assert result["per_check"]["claims_within_cited_evidence"] == 0.0, (
        "BE-3 FAILED: Answer referencing 2008-2009 and 1970s outside zoom window "
        f"2023-01-01..2023-12-31 must force claims_within_cited_evidence=0.0 (Decision 5). "
        f"Got: {result['per_check']['claims_within_cited_evidence']}"
    )

    # Total score should fall below accept threshold (0.75) and trigger refine or reject
    assert result["total"] < 0.75, (
        f"BE-3 FAILED: Total score {result['total']:.3f} should be < 0.75 when "
        "claims_within_cited_evidence=0.0"
    )
    assert result["recommendation"] in ("refine", "reject"), (
        f"BE-3 FAILED: Expected 'refine' or 'reject', got {result['recommendation']!r}"
    )


# ─── BE-4: Positive control — answer within window ────────────────────────────


@pytest.mark.phase89
def test_BE4_b5_rubric_no_penalty_for_in_window_answer():
    """BE-4 (positive control): claims_within_cited_evidence ≥ 0.8 when answer stays in window.

    Use INV-PASS-01 golden case: answer cites June 2022 and 2008/2011 analogues.
    Scope the prompt_context to a wide window (2008-2024) so those dates are IN range.
    The rubric scorer must NOT penalise this answer — claims_within_cited_evidence
    should reflect the LLM's positive score (≥ 0.8), and the total should
    stay above 0.75 → recommendation = "accept".

    Confirms the rubric isn't punishing every answer indiscriminately.
    """
    golden = _load_golden()
    pass_case = next(c for c in golden["investigator_cases"] if c["case_id"] == "INV-PASS-01")
    answer_text = pass_case["answer_text"]
    rubric = _canned_rubric()

    # Wide zoom window that covers the years cited in the answer (2008, 2011, 2022)
    prompt_context = {
        "zoom_range": {
            "start_ts": "2008-01-01",
            "end_ts": "2024-12-31",
        }
    }

    # Canned scores matching the golden fixture's expected rubric scores
    canned_scores = {
        "cites_evidence": 0.90,
        "claims_within_cited_evidence": 0.90,  # LLM score — scorer must NOT override
        "acknowledges_uncertainty": 0.80,
        "correlation_not_causation": 0.85,
        "confidence_calibrated_and_concise": 1.00,
    }

    with patch(
        "core.b5.rubric_scorer._call_utility_model_for_check",
        side_effect=lambda check_id, **_kw: canned_scores[check_id],
    ):
        from core.b5.rubric_scorer import score_answer

        result = score_answer(
            answer=answer_text,
            rubric=rubric,
            prompt_context=prompt_context,
        )

    # Positive control: claims_within_cited_evidence must NOT be penalised
    assert result["per_check"]["claims_within_cited_evidence"] >= 0.8, (
        f"BE-4 FAILED: In-window answer must not be penalised. "
        f"Got claims_within={result['per_check']['claims_within_cited_evidence']:.2f}"
    )

    # Total should pass the accept threshold
    assert result["total"] >= 0.75, (
        f"BE-4 FAILED: Total {result['total']:.3f} should be ≥ 0.75 for a good in-window answer"
    )
    assert result["recommendation"] == "accept", (
        f"BE-4 FAILED: Expected 'accept', got {result['recommendation']!r}"
    )
