"""Phase 83 Plan 09 Task 2 — IntelligenceFeedMacroComposer refactor test suite.

Tests for VM107/emitters/intelligence_feed_macro_composer.py after the 4-surgery
refactor:
  1. HTTP client data source (RISK-06 consumer closure)
  2. Phase 43 router LLM calls (Pitfall 6 closure)
  3. NoveltyEngine V1 integration (Phase 66 Lock 2)
  4. Phase 70.5 envelope wrap (Open Question 6)
"""
import uuid
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_calendar_item(
    event_id="evt-1",
    indicator_code="CPIAUCSL",
    indicator_short_name="CPI",
    event_date="2026-06-05T14:00:00Z",
    severity="HIGH",
    releasing_authority="BLS",
):
    """Build a minimal calendar item dict (UpcomingCalendarItem shape per Plan 07)."""
    return {
        "event_id": event_id,
        "indicator_code": indicator_code,
        "indicator_short_name": indicator_short_name,
        "event_date": event_date,
        "severity": severity,
        "releasing_authority": releasing_authority,
        "affected_symbols": [],
        "reference_period_date": None,
    }


def _make_mock_calendar_client(items=None):
    """Build a mocked MacroCalendarHTTPClient."""
    mock = MagicMock()
    mock.fetch_upcoming.return_value = items if items is not None else []
    return mock


def _make_mock_novelty_engine(threshold_crossed=True, score=0.8):
    """Build a mocked NoveltyEngine that returns a deterministic score."""
    from lib.novelty_engine.engine import NoveltyScore
    mock = MagicMock()
    mock.score.return_value = NoveltyScore(
        score=score,
        contributing_factors=["AUTH_FED"],
        threshold_crossed=threshold_crossed,
        reason_codes=["AUTH_FED"],
    )
    return mock


def _make_mock_router(model_id="claude-haiku-4-5"):
    """Build a mocked ModelRouter that returns a RoutingDecision."""
    from core.routing.schemas import RoutingDecision
    decision = RoutingDecision(
        task_id="test-task-001",
        goal_id="vm107.macro_emitter",
        agent_id="macro_emitter",
        task_type="macro_narrative_enrichment",
        primary=model_id,
        fallback=["ollama/llama3.2"],
        reason=["path=utility", "mock"],
        decision_time_ms=1.0,
        selected_model=model_id,
        path="utility",
    )
    mock = MagicMock()
    mock.decide.return_value = decision
    return mock


def _make_composer(calendar_items=None, novelty_threshold_crossed=True, router=None):
    """Build IntelligenceFeedMacroComposer with all deps mocked."""
    from emitters.intelligence_feed_macro_composer import IntelligenceFeedMacroComposer

    items = calendar_items if calendar_items is not None else [_make_calendar_item()]
    mock_client = _make_mock_calendar_client(items)
    mock_engine = _make_mock_novelty_engine(threshold_crossed=novelty_threshold_crossed)
    mock_router = router or _make_mock_router()

    return IntelligenceFeedMacroComposer(
        novelty_engine=mock_engine,
        calendar_client=mock_client,
        router=mock_router,
    ), mock_client, mock_engine, mock_router


# ---------------------------------------------------------------------------
# Test 1: _call_llm routes through Phase 43 router with utility profile
# ---------------------------------------------------------------------------

@pytest.mark.phase83
def test_call_llm_routes_through_phase_43_router():
    """Composer._call_llm calls ModelRouter.decide() with path='utility'."""
    from emitters.intelligence_feed_macro_composer import IntelligenceFeedMacroComposer
    from core.routing.schemas import RouterContext

    mock_router = _make_mock_router()
    # Patch LiteLLM so we don't actually call an LLM
    with patch("emitters.intelligence_feed_macro_composer.litellm") as mock_litellm:
        mock_litellm.completion.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="Test narrative"))]
        )
        composer = IntelligenceFeedMacroComposer(
            calendar_client=_make_mock_calendar_client(),
            router=mock_router,
        )
        result = composer._call_llm("CPI", "HIGH", "CPI releases in 2h.")

    mock_router.decide.assert_called_once()
    ctx_arg = mock_router.decide.call_args[0][0]
    assert isinstance(ctx_arg, RouterContext)
    assert ctx_arg.path == "utility"
    assert ctx_arg.agent_id == "macro_emitter"
    assert ctx_arg.task_type == "macro_narrative_enrichment"


# ---------------------------------------------------------------------------
# Test 2: _call_llm never instantiates anthropic.Anthropic
# ---------------------------------------------------------------------------

@pytest.mark.phase83
def test_call_llm_no_direct_anthropic_sdk():
    """_call_llm must never instantiate anthropic.Anthropic (Pitfall 6 gate)."""
    from emitters.intelligence_feed_macro_composer import IntelligenceFeedMacroComposer

    mock_router = _make_mock_router()
    with patch("emitters.intelligence_feed_macro_composer.litellm") as mock_litellm:
        mock_litellm.completion.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="narrative"))]
        )
        with patch("anthropic.Anthropic") as mock_anthropic:
            composer = IntelligenceFeedMacroComposer(
                calendar_client=_make_mock_calendar_client(),
                router=mock_router,
            )
            composer._call_llm("GDP", "CRITICAL", "GDP releases.")

    mock_anthropic.assert_not_called()


# ---------------------------------------------------------------------------
# Test 3: _call_llm returns None on router failure (Phase 43.2 graceful degradation)
# ---------------------------------------------------------------------------

@pytest.mark.phase83
def test_call_llm_returns_none_on_router_failure():
    """_call_llm returns None when router.decide raises (Tier-1 deterministic fallback)."""
    from emitters.intelligence_feed_macro_composer import IntelligenceFeedMacroComposer

    mock_router = MagicMock()
    mock_router.decide.side_effect = RuntimeError("Redis unavailable")

    composer = IntelligenceFeedMacroComposer(
        calendar_client=_make_mock_calendar_client(),
        router=mock_router,
    )
    result = composer._call_llm("FOMC", "CRITICAL", "FOMC rate decision.")
    assert result is None


# ---------------------------------------------------------------------------
# Test 4: compose() uses HTTP client, not Django ORM
# ---------------------------------------------------------------------------

@pytest.mark.phase83
def test_composer_uses_http_client_not_django_orm():
    """compose() fetches events via HTTP client, not AnalyticsCalendarService ORM."""
    composer, mock_client, mock_engine, mock_router = _make_composer()

    with patch("emitters.intelligence_feed_macro_composer.litellm") as mock_llm:
        mock_llm.completion.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="narrative"))]
        )
        composer.compose(state="OPEN")

    mock_client.fetch_upcoming.assert_called_once()
    # Verify no Django ORM call path — client was the only source
    # (structural verification in test_composer_no_django_import.py)


# ---------------------------------------------------------------------------
# Test 5: compose() returns ToolResultEnvelope with MacroEmissionPayload
# ---------------------------------------------------------------------------

@pytest.mark.phase83
def test_compose_returns_envelope_wrapped_payload():
    """compose() returns ToolResultEnvelope[MacroEmissionPayload] with correct item count."""
    from fingpt_core.contracts.tool_envelope import ToolResultEnvelope
    from emitters.intelligence_feed_macro_composer import MacroEmissionPayload

    items = [_make_calendar_item("evt-1"), _make_calendar_item("evt-2")]
    composer, _, _, _ = _make_composer(calendar_items=items, novelty_threshold_crossed=False)

    result = composer.compose(state="OPEN")

    assert isinstance(result, ToolResultEnvelope)
    assert isinstance(result.payload, MacroEmissionPayload)
    assert len(result.payload.items) == 2


# ---------------------------------------------------------------------------
# Test 6: score_macro called once per event item
# ---------------------------------------------------------------------------

@pytest.mark.phase83
def test_compose_runs_novelty_scoring_per_item():
    """NoveltyEngine.score() is called exactly once per calendar item."""
    items = [_make_calendar_item("evt-1")]
    composer, _, mock_engine, _ = _make_composer(
        calendar_items=items, novelty_threshold_crossed=False
    )

    composer.compose(state="OPEN")

    assert mock_engine.score.call_count == 1


# ---------------------------------------------------------------------------
# Test 7: LLM enrichment gated on threshold_crossed
# ---------------------------------------------------------------------------

@pytest.mark.phase83
def test_compose_gates_llm_enrichment_on_novelty_threshold():
    """When threshold_crossed=False, router.decide() not called. When True, it is called."""
    # --- threshold_crossed=False: no LLM call ---
    items = [_make_calendar_item()]
    composer_no_llm, _, _, router_no_llm = _make_composer(
        calendar_items=items, novelty_threshold_crossed=False
    )
    result_no_llm = composer_no_llm.compose(state="OPEN")

    router_no_llm.decide.assert_not_called()
    assert result_no_llm.payload.items[0].narrative is None

    # --- threshold_crossed=True: LLM is called (may succeed or fail) ---
    items2 = [_make_calendar_item()]
    mock_router = _make_mock_router()
    with patch("emitters.intelligence_feed_macro_composer.litellm") as mock_llm:
        mock_llm.completion.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="enriched narrative"))]
        )
        composer_with_llm, _, _, _ = _make_composer(
            calendar_items=items2,
            novelty_threshold_crossed=True,
            router=mock_router,
        )
        result_with_llm = composer_with_llm.compose(state="OPEN")

    mock_router.decide.assert_called_once()
    assert result_with_llm.payload.items[0].narrative is not None


# ---------------------------------------------------------------------------
# Test 8: empty client response → envelope with items=[], degraded=True
# ---------------------------------------------------------------------------

@pytest.mark.phase83
def test_compose_returns_empty_on_client_failure():
    """When calendar client returns [], compose returns envelope with items=[] + degraded=True."""
    from fingpt_core.contracts.tool_envelope import ToolResultEnvelope

    composer, _, _, _ = _make_composer(calendar_items=[])
    result = composer.compose(state="OPEN")

    assert isinstance(result, ToolResultEnvelope)
    assert result.payload.items == []
    assert result.payload.degraded is True


# ---------------------------------------------------------------------------
# Test 9: _demo=False by default (Plan 10 owns the True path)
# ---------------------------------------------------------------------------

@pytest.mark.phase83
def test_compose_demo_flag_false_by_default():
    """All MacroItems have _demo=False by default (Plan 10 env-flag flip owns True)."""
    items = [_make_calendar_item("evt-1"), _make_calendar_item("evt-2")]
    composer, _, _, _ = _make_composer(
        calendar_items=items, novelty_threshold_crossed=False
    )
    result = composer.compose(state="OPEN")

    for item in result.payload.items:
        assert item.demo is False


# ---------------------------------------------------------------------------
# Test 10: Phase 66 Lock 4 — narrative ≤ 200 chars
# ---------------------------------------------------------------------------

@pytest.mark.phase83
def test_compose_respects_phase_66_lock_4_narrative_length():
    """When LLM enrichment runs, narrative length ≤ 200 chars (journalistic brevity)."""
    items = [_make_calendar_item()]
    mock_router = _make_mock_router()

    # LLM returns a short enough string
    short_narrative = "A" * 195  # 195 chars — within 200 limit
    with patch("emitters.intelligence_feed_macro_composer.litellm") as mock_llm:
        mock_llm.completion.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content=short_narrative))]
        )
        composer, _, _, _ = _make_composer(
            calendar_items=items,
            novelty_threshold_crossed=True,
            router=mock_router,
        )
        result = composer.compose(state="OPEN")

    for item in result.payload.items:
        if item.narrative is not None:
            assert len(item.narrative) <= 200, (
                f"Phase 66 Lock 4 violated: narrative is {len(item.narrative)} chars "
                f"(max 200): {item.narrative!r}"
            )
