"""Phase 48 Plan 07 — 10 typed emit helpers for refinement lifecycle events.

Each helper wraps core.events.phase56_client.emit_event with a hardcoded
event_type string + a typed Pydantic payload + causality_scope='IDEA'.

REQ-48-D18 (orchestrator sole emitter; lifecycle correlation_id=loop_id).
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

import pytest


# ---------------------------------------------------------------------------
# Per-helper parametrize matrix: (helper_name, expected_event_type,
# expected_category, kwargs_for_call, expected_payload_subset_keys).
# ---------------------------------------------------------------------------

LOOP_ID = "loop-phase48-07-test"
ROOT_HYP = "hyp-phase48-07"
SNAP_HASH = "snap-deadbeef"

HELPER_CASES: list[tuple[str, str, str, dict, set[str]]] = [
    (
        "emit_refinement_loop_started",
        "refinement_loop_started",
        "cognition",
        {
            "loop_id": LOOP_ID,
            "task_id": "task-001",
            "root_hypothesis_id": ROOT_HYP,
            "strategy_family": "BREAKOUT",
            "registry_snapshot_hash": SNAP_HASH,
        },
        {"loop_id", "task_id", "root_hypothesis_id", "strategy_family", "registry_snapshot_hash"},
    ),
    (
        "emit_iteration_started",
        "iteration_started",
        "cognition",
        {
            "loop_id": LOOP_ID,
            "iteration_number": 0,
            "root_hypothesis_id": ROOT_HYP,
            "registry_snapshot_hash": SNAP_HASH,
        },
        {"loop_id", "iteration_number", "root_hypothesis_id", "registry_snapshot_hash"},
    ),
    (
        "emit_critic_verdict_received",
        "critic_verdict_received",
        "cognition",
        {
            "loop_id": LOOP_ID,
            "iteration_number": 1,
            "critic_verdict_id": "cv-001",
            "verdict": "REFINE",
            "confidence": 0.75,
            "refinement_targets_count": 2,
        },
        {"loop_id", "iteration_number", "critic_verdict_id", "verdict", "confidence", "refinement_targets_count"},
    ),
    (
        "emit_hard_veto_triggered",
        "hard_veto_triggered",
        "cognition",
        {
            "loop_id": LOOP_ID,
            "iteration_number": 2,
            "vetoes_triggered": [
                {"metric": "max_drawdown", "threshold": 0.20, "actual": 0.34},
            ],
        },
        {"loop_id", "iteration_number", "vetoes_triggered"},
    ),
    (
        "emit_identity_drift_detected",
        "identity_drift_detected",
        "cognition",
        {
            "loop_id": LOOP_ID,
            "iteration_number": 2,
            "identity_score": 0.62,
            "threshold": 0.80,
            "identity_diff_breakdown": {"IMMUTABLE_CORE": 0.30, "REFINABLE": 0.05, "MINOR_TUNING": 0.03},
        },
        {"loop_id", "iteration_number", "identity_score", "threshold", "identity_diff_breakdown"},
    ),
    (
        "emit_convergence_stall_detected",
        "convergence_stall_detected",
        "cognition",
        {
            "loop_id": LOOP_ID,
            "iteration_number": 2,
            "repeated_targets": [
                {"scope": "STRATEGY_SPEC", "canonical_issue_id": "OVERFIT_SIGNATURE", "issue_type": "ROBUSTNESS"},
            ],
        },
        {"loop_id", "iteration_number", "repeated_targets"},
    ),
    (
        "emit_budget_exceeded",
        "budget_exceeded",
        "cognition",
        {
            "loop_id": LOOP_ID,
            "iteration_number": 1,
            "scope": "ITERATION",
            "consumed_usd": 0.85,
            "cap_usd": 0.50,
        },
        {"loop_id", "iteration_number", "scope", "consumed_usd", "cap_usd"},
    ),
    (
        "emit_strategy_accepted",
        "strategy_accepted",
        "lifecycle",
        {
            "loop_id": LOOP_ID,
            "accepted_strategy_id": "strat-001",
            "root_hypothesis_id": ROOT_HYP,
            "final_iteration": 2,
            "registry_yaml_path": "VM107/registry/strategy/strat-001.yaml",
        },
        {"loop_id", "accepted_strategy_id", "root_hypothesis_id", "final_iteration", "registry_yaml_path"},
    ),
    (
        "emit_strategy_rejected",
        "strategy_rejected",
        "lifecycle",
        {
            "loop_id": LOOP_ID,
            "rejected_strategy_id": "strat-002",
            "root_hypothesis_id": ROOT_HYP,
            "termination_reason": "HARD_VETO",
            "final_iteration": 1,
        },
        {"loop_id", "rejected_strategy_id", "root_hypothesis_id", "termination_reason", "final_iteration"},
    ),
    (
        "emit_loop_terminated",
        "loop_terminated",
        "lifecycle",
        {
            "loop_id": LOOP_ID,
            "termination_reason": "MAX_ITERATIONS",
            "final_iteration": 3,
            "total_cost_usd": 1.42,
        },
        {"loop_id", "termination_reason", "final_iteration", "total_cost_usd"},
    ),
]


def test_module_imports_all_10_helpers():
    """All 10 typed emit helpers are importable from core.events.refinement_events."""
    from core.events import refinement_events as re
    for helper_name, *_ in HELPER_CASES:
        assert callable(getattr(re, helper_name)), (
            f"core.events.refinement_events missing helper: {helper_name}"
        )


@pytest.mark.parametrize(
    "helper_name,expected_event_type,expected_category,kwargs,expected_payload_keys",
    HELPER_CASES,
)
def test_helper_calls_emit_event_with_correct_event_type(
    monkeypatch,
    helper_name,
    expected_event_type,
    expected_category,
    kwargs,
    expected_payload_keys,
):
    """Each helper invokes emit_event once with the expected event_type + payload shape."""
    mock_emit = MagicMock(name="emit_event")
    monkeypatch.setattr("core.events.refinement_events.emit_event", mock_emit)

    from core.events import refinement_events as re

    helper = getattr(re, helper_name)
    helper(**kwargs)

    assert mock_emit.call_count == 1, (
        f"{helper_name}: expected emit_event to be called exactly once, "
        f"got {mock_emit.call_count} calls"
    )
    call = mock_emit.call_args
    # All helpers MUST pass event_type, category, correlation_id, payload, causality_scope.
    call_kwargs = call.kwargs
    assert call_kwargs["event_type"] == expected_event_type
    assert call_kwargs["category"] == expected_category
    assert call_kwargs["correlation_id"] == LOOP_ID, (
        f"{helper_name}: correlation_id must equal loop_id (Phase 56 lock)"
    )
    assert call_kwargs["causality_scope"] == "IDEA", (
        f"{helper_name}: causality_scope must equal 'IDEA' (planner V1 lock)"
    )
    payload = call_kwargs["payload"]
    assert isinstance(payload, dict)
    assert set(payload.keys()) == expected_payload_keys, (
        f"{helper_name}: payload keys {sorted(payload.keys())} "
        f"!= expected {sorted(expected_payload_keys)}"
    )


@pytest.mark.parametrize(
    "helper_name,expected_event_type,expected_category,kwargs,expected_payload_keys",
    HELPER_CASES,
)
def test_helper_payload_round_trips_via_pydantic_model(
    monkeypatch,
    helper_name,
    expected_event_type,
    expected_category,
    kwargs,
    expected_payload_keys,
):
    """Helper payloads pass through a Pydantic model — validates types at call site."""
    mock_emit = MagicMock(name="emit_event")
    monkeypatch.setattr("core.events.refinement_events.emit_event", mock_emit)

    from core.events import refinement_events as re

    helper = getattr(re, helper_name)
    helper(**kwargs)

    payload = mock_emit.call_args.kwargs["payload"]
    # Pydantic .model_dump() returns plain JSON-compatible types.
    for k, v in payload.items():
        # Inner dicts (e.g., identity_diff_breakdown) and lists are allowed.
        assert v is not None or k in {"termination_reason"}, (
            f"{helper_name}: payload[{k!r}] is None (must be non-null unless documented)"
        )


def test_helpers_invalid_payload_raises():
    """Helpers reject mistyped inputs via Pydantic ValidationError."""
    from core.events import refinement_events as re
    from pydantic import ValidationError

    # confidence is a float [0.0, 1.0] — string here must fail.
    with pytest.raises(ValidationError):
        re.emit_critic_verdict_received(
            loop_id=LOOP_ID,
            iteration_number=0,
            critic_verdict_id="cv",
            verdict="ACCEPT",
            confidence="not-a-float",  # type: ignore[arg-type]
            refinement_targets_count=0,
        )

    # iteration_number negative — must fail.
    with pytest.raises(ValidationError):
        re.emit_iteration_started(
            loop_id=LOOP_ID,
            iteration_number=-1,
            root_hypothesis_id=ROOT_HYP,
            registry_snapshot_hash=SNAP_HASH,
        )


def test_helpers_form_complete_lifecycle(monkeypatch):
    """Sequence: loop_started -> iteration_started -> critic_verdict_received ->
    strategy_accepted -> loop_terminated forms a coherent lifecycle.

    Asserts the 5 helpers can be invoked in order against a single mocked
    emit_event and yields the expected event_type sequence.
    """
    mock_emit = MagicMock(name="emit_event")
    monkeypatch.setattr("core.events.refinement_events.emit_event", mock_emit)

    from core.events import refinement_events as re

    re.emit_refinement_loop_started(
        loop_id=LOOP_ID,
        task_id="task-001",
        root_hypothesis_id=ROOT_HYP,
        strategy_family="BREAKOUT",
        registry_snapshot_hash=SNAP_HASH,
    )
    re.emit_iteration_started(
        loop_id=LOOP_ID,
        iteration_number=0,
        root_hypothesis_id=ROOT_HYP,
        registry_snapshot_hash=SNAP_HASH,
    )
    re.emit_critic_verdict_received(
        loop_id=LOOP_ID,
        iteration_number=0,
        critic_verdict_id="cv-0",
        verdict="ACCEPT",
        confidence=0.91,
        refinement_targets_count=0,
    )
    re.emit_strategy_accepted(
        loop_id=LOOP_ID,
        accepted_strategy_id="strat-A",
        root_hypothesis_id=ROOT_HYP,
        final_iteration=0,
        registry_yaml_path="VM107/registry/strategy/strat-A.yaml",
    )
    re.emit_loop_terminated(
        loop_id=LOOP_ID,
        termination_reason="ACCEPTED",
        final_iteration=0,
        total_cost_usd=0.12,
    )

    event_sequence = [c.kwargs["event_type"] for c in mock_emit.call_args_list]
    assert event_sequence == [
        "refinement_loop_started",
        "iteration_started",
        "critic_verdict_received",
        "strategy_accepted",
        "loop_terminated",
    ]
    # Every event in the lifecycle carries the same correlation_id == loop_id.
    correlation_ids = {c.kwargs["correlation_id"] for c in mock_emit.call_args_list}
    assert correlation_ids == {LOOP_ID}
    # Every event in the lifecycle carries causality_scope='IDEA'.
    scopes = {c.kwargs["causality_scope"] for c in mock_emit.call_args_list}
    assert scopes == {"IDEA"}
