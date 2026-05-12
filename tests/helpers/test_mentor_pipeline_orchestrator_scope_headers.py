"""Phase 60.1 G7+G10+G22: verify X-Agent-Scope flows from ScopeDispatcher
through the orchestrator into both the subordinate invoker and the persister.

TDD RED → GREEN phase for plan 60-16.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

import pytest
from datetime import datetime, timedelta, timezone
from uuid import uuid4


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("SCOPE_DISPATCHER_SECRET_KEY", "test-secret-not-prod")
    monkeypatch.setenv("VM100_INTERNAL_BASE_URL", "http://test-vm100:8000")


def _build_minimal_scope_context():
    """Build a minimal ScopeContext with only required fields."""
    from fingpt_core.contracts.narrative.scope import ScopeContext, TruthMode
    return ScopeContext(
        profile_id="trade_auditor_agent",
        account_id="acc-001",
        execution_id=None,
        truth_mode=TruthMode.HISTORICAL,
        issued_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )


_REGISTRY_ROOT = _VM107_ROOT / "registry"


def _build_orchestrator_with_real_dispatcher():
    """Build orchestrator with real ScopeDispatcher (needs SCOPE_DISPATCHER_SECRET_KEY)."""
    from helpers.scope_dispatcher import ScopeDispatcher
    from helpers.mentor_pipeline_orchestrator import MentorPipelineOrchestrator
    from helpers.citation_validator import CitationValidator
    from helpers.confidence_vector_calculator import ConfidenceVectorCalculator

    sub_invoker = AsyncMock()
    persister = AsyncMock()
    emitter = MagicMock()
    emitter.new_correlation_id = MagicMock(return_value="cor-1")
    dispatcher = ScopeDispatcher()

    orch = MentorPipelineOrchestrator(
        profile="trade_auditor_agent",
        scope_dispatcher=dispatcher,
        citation_validator=CitationValidator(_REGISTRY_ROOT),
        confidence_calculator=ConfidenceVectorCalculator(),
        event_emitter=emitter,
        subordinate_invoker=sub_invoker,
        narrative_persister_client=persister,
    )
    return orch, sub_invoker, persister, emitter


# ── Test 1: _prepare_scope_headers returns dict with X-Agent-Scope ─────────

@pytest.mark.asyncio
async def test_prepare_scope_headers_contains_x_agent_scope():
    """_prepare_scope_headers returns a non-empty dict with X-Agent-Scope JWT."""
    orch, _, _, _ = _build_orchestrator_with_real_dispatcher()

    headers = orch._prepare_scope_headers(_build_minimal_scope_context(), "cor-1")
    assert isinstance(headers, dict)
    assert "X-Agent-Scope" in headers
    assert isinstance(headers["X-Agent-Scope"], str)
    assert len(headers["X-Agent-Scope"]) > 0


# ── Test 2: _prepare_scope_headers with None dispatcher emits failure ───────

def test_prepare_scope_headers_no_dispatcher_emits_failure():
    """When scope_dispatcher=None, _prepare_scope_headers returns {} and emits scope_validation_failed."""
    from helpers.mentor_pipeline_orchestrator import MentorPipelineOrchestrator
    from helpers.citation_validator import CitationValidator
    from helpers.confidence_vector_calculator import ConfidenceVectorCalculator

    emitter = MagicMock()
    emitter.new_correlation_id = MagicMock(return_value="cor-x")

    orch = MentorPipelineOrchestrator(
        profile="trade_auditor_agent",
        scope_dispatcher=None,
        citation_validator=CitationValidator(_REGISTRY_ROOT),
        confidence_calculator=ConfidenceVectorCalculator(),
        event_emitter=emitter,
        subordinate_invoker=AsyncMock(),
        narrative_persister_client=AsyncMock(),
    )

    headers = orch._prepare_scope_headers(_build_minimal_scope_context(), "cor-x")
    assert headers == {}
    # scope_validation_failed event must be emitted at least once
    emitted_event_types = [
        call.kwargs.get("event_type") or (call.args[0] if call.args else None)
        for call in emitter.emit.call_args_list
    ]
    assert "scope_validation_failed" in emitted_event_types, (
        f"Expected 'scope_validation_failed' in emitted events, got: {emitted_event_types}"
    )


# ── Test 3: subordinate_invoker is called with headers kwarg ────────────────

@pytest.mark.asyncio
async def test_subordinate_invoker_receives_scope_headers():
    """orchestrator.run() passes scope_headers as headers= kwarg to subordinate_invoker."""
    from helpers.scope_dispatcher import ScopeDispatcher
    from helpers.mentor_pipeline_orchestrator import MentorPipelineOrchestrator
    from helpers.citation_validator import CitationValidator
    from helpers.confidence_vector_calculator import ConfidenceVectorCalculator
    from fingpt_core.contracts.narrative.scope import TruthMode

    # sub_invoker raises after first call to abort the run quickly;
    # we just need to confirm the FIRST call carried headers
    call_count = [0]

    async def capturing_invoker(**kwargs):
        call_count[0] += 1
        # Return minimally valid ReaderOutput dict to proceed past reader stage
        from fingpt_core.contracts.narrative.scope import ScopeContext
        scope = _build_minimal_scope_context()
        return {
            "execution_id": None,
            "scope_context": scope.model_dump(),
            "retrieved_evidence": {},
        }

    persister = AsyncMock()
    emitter = MagicMock()
    emitter.new_correlation_id = MagicMock(return_value="cor-2")

    # We need a spy on the invoker to capture kwargs
    captured_calls = []

    async def spying_invoker(*args, **kwargs):
        captured_calls.append({"args": args, "kwargs": kwargs})
        return await capturing_invoker(**kwargs)

    orch = MentorPipelineOrchestrator(
        profile="trade_auditor_agent",
        scope_dispatcher=ScopeDispatcher(),
        citation_validator=CitationValidator(_REGISTRY_ROOT),
        confidence_calculator=ConfidenceVectorCalculator(),
        event_emitter=emitter,
        subordinate_invoker=spying_invoker,
        narrative_persister_client=persister,
    )

    try:
        await orch.run(
            execution_id=None,
            scope_context=_build_minimal_scope_context(),
            replay_artifact_id=None,
            ruleset_version="r1",
            analysis_version=1,
            template_version="1.0.0",
            source_snapshot_id=uuid4(),
            truth_mode=TruthMode.HISTORICAL,
            replay_metadata={},
            regime_snapshot_age_hours=2.0,
        )
    except Exception:
        pass  # we only care about the first invoker call

    assert len(captured_calls) >= 1, "subordinate_invoker was never called"
    first_call = captured_calls[0]
    # The invoker must have been called with headers= kwarg
    assert "headers" in first_call["kwargs"], (
        f"subordinate_invoker not called with headers kwarg; kwargs={first_call['kwargs']}"
    )
    headers_val = first_call["kwargs"]["headers"]
    assert isinstance(headers_val, dict), f"headers must be a dict, got {type(headers_val)}"
    assert "X-Agent-Scope" in headers_val, (
        f"X-Agent-Scope not present in headers; got keys: {list(headers_val.keys())}"
    )


# ── Test 4: narrative_persister_client.persist receives headers kwarg ───────

@pytest.mark.asyncio
async def test_persister_receives_scope_headers(tmp_path):
    """orchestrator.run() passes scope_headers as headers= kwarg to persister.persist()."""
    from helpers.scope_dispatcher import ScopeDispatcher
    from helpers.mentor_pipeline_orchestrator import MentorPipelineOrchestrator
    from helpers.citation_validator import CitationValidator
    from helpers.confidence_vector_calculator import ConfidenceVectorCalculator
    from fingpt_core.contracts.narrative.scope import TruthMode
    from fingpt_core.contracts.narrative.sentence import NarrativeSentence, SentenceClass

    scope_context = _build_minimal_scope_context()
    execution_id = uuid4()

    async def happy_invoker(*args, **kwargs):
        profile = kwargs.get("profile", args[0] if args else "")
        if "_reader" in profile:
            return {
                "execution_id": str(execution_id),
                "scope_context": scope_context.model_dump(),
                "retrieved_evidence": {},
            }
        if "_analyzer" in profile:
            return {
                "execution_id": str(execution_id),
                "scope_context": scope_context.model_dump(),
                "findings": {},
                "cited_registry_ids": [],
            }
        # _writer: TRANSITION sentence (no citation required)
        return {
            "profile": "trade_auditor_agent",
            "execution_id": str(execution_id),
            "sentences": [
                {
                    "sentence_index": 0,
                    "sentence_class": "TRANSITION",
                    "text": "Trade was well managed.",
                    "citations": [],
                }
            ],
            "confidence_vector": None,
            "unsourced_claim_count": 0,
        }

    persister_calls = []

    async def capturing_persister(**kwargs):
        persister_calls.append(kwargs)
        return None

    persister = MagicMock()
    persister.persist = capturing_persister

    emitter = MagicMock()
    emitter.new_correlation_id = MagicMock(return_value="cor-3")

    orch = MentorPipelineOrchestrator(
        profile="trade_auditor_agent",
        scope_dispatcher=ScopeDispatcher(),
        citation_validator=CitationValidator(tmp_path),
        confidence_calculator=ConfidenceVectorCalculator(),
        event_emitter=emitter,
        subordinate_invoker=happy_invoker,
        narrative_persister_client=persister,
    )

    await orch.run(
        execution_id=execution_id,
        scope_context=scope_context,
        replay_artifact_id=None,
        ruleset_version="r1",
        analysis_version=1,
        template_version="1.0.0",
        source_snapshot_id=uuid4(),
        truth_mode=TruthMode.HISTORICAL,
        replay_metadata={},
        regime_snapshot_age_hours=2.0,
    )

    assert len(persister_calls) >= 1, "persister.persist() was never called"
    call_kwargs = persister_calls[0]
    assert "headers" in call_kwargs, (
        f"persister.persist not called with headers kwarg; got keys: {list(call_kwargs.keys())}"
    )
    headers_val = call_kwargs["headers"]
    assert isinstance(headers_val, dict), f"headers must be a dict, got {type(headers_val)}"
    assert "X-Agent-Scope" in headers_val, (
        f"X-Agent-Scope not present in persister headers; got keys: {list(headers_val.keys())}"
    )


# ── Parametrized tool forwarding test (silent-partial-coverage guard) ────────

@pytest.mark.parametrize("module_path,class_name,method_name,build_request", [
    (
        "tools.persist_narrative",
        "PersistNarrativeTool",
        "persist",
        None,  # special-cased below
    ),
    (
        "tools.get_behavioral_edges",
        "GetBehavioralEdgesTool",
        "call",
        "behavioral_edges",
    ),
    (
        "tools.get_cross_trade_behavioral_patterns",
        "GetCrossTradeBehavioralPatternsTool",
        "call",
        "cross_trade_patterns",
    ),
    (
        "tools.get_weekly_execution_summary",
        "GetWeeklyExecutionSummaryTool",
        "call",
        "weekly_summary",
    ),
])
@pytest.mark.asyncio
async def test_tool_forwards_headers_to_httpx(
    module_path, class_name, method_name, build_request
):
    """Each Phase 60 standalone tool forwards the headers kwarg into its httpx call.

    This is the silent-partial-coverage guard (plan 60-16 decision): if any of the
    4 tool-file edits is forgotten, this parametrize row fails.
    """
    import importlib
    from datetime import date
    from uuid import uuid4
    from fingpt_core.contracts.narrative.scope import ScopeContext, TruthMode
    from fingpt_core.contracts.narrative.envelope import NarrativeEnvelope

    scope_context = ScopeContext(
        profile_id="trade_auditor_agent",
        account_id="acc-001",
        execution_id=None,
        truth_mode=TruthMode.HISTORICAL,
        issued_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )

    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)
    instance = cls()
    method = getattr(instance, method_name)

    captured = {}

    async def _fake_http_call(url, *args, **kwargs):
        captured["headers"] = kwargs.get("headers")
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        if class_name == "PersistNarrativeTool":
            resp.json = MagicMock(return_value={
                "narrative_id": str(uuid4()),
                "narrative_version": 1,
                "unsourced_claim_count": 0,
            })
        elif class_name == "GetBehavioralEdgesTool":
            resp.json = MagicMock(return_value=[])
        elif class_name == "GetCrossTradeBehavioralPatternsTool":
            resp.json = MagicMock(return_value=[])
        elif class_name == "GetWeeklyExecutionSummaryTool":
            resp.json = MagicMock(return_value={
                "account_id": "acc-001",
                "week_start": "2026-01-06",
                "week_end": "2026-01-12",
                "executions": [],
            })
        return resp

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=_fake_http_call)
    mock_client.get = AsyncMock(side_effect=_fake_http_call)

    with patch(f"{module_path}.httpx.AsyncClient", return_value=mock_client):
        try:
            if build_request is None:
                # PersistNarrativeTool — build a PersistNarrativeRequest
                from tools.persist_narrative import PersistNarrativeRequest
                from fingpt_core.contracts.narrative.envelope import NarrativeEnvelope
                from fingpt_core.contracts.narrative.sentence import NarrativeSentence, SentenceClass
                envelope = NarrativeEnvelope(
                    profile="trade_auditor_agent",
                    execution_id=None,
                    sentences=[
                        NarrativeSentence(
                            sentence_index=0,
                            sentence_class=SentenceClass.TRANSITION,
                            text="Trade was well managed.",
                            citations=[],
                        )
                    ],
                    confidence_vector=None,
                    unsourced_claim_count=0,
                )
                request = PersistNarrativeRequest(
                    envelope=envelope,
                    scope_context=scope_context,
                    ruleset_version="r1",
                    analysis_version=1,
                    template_version="1.0.0",
                    scope_origin="{}",
                    truth_mode="HISTORICAL",
                    source_snapshot_id=uuid4(),
                    source_replay_artifact_id=uuid4(),
                    generated_by="test",
                    generated_reason="TEST",
                    writer_profile_id="trade_auditor_agent._writer",
                )
                await method(request, headers={"X-Agent-Scope": "JWT-TEST"})

            elif build_request == "behavioral_edges":
                from tools.get_behavioral_edges import GetBehavioralEdgesRequest
                request = GetBehavioralEdgesRequest(
                    execution_id=uuid4(),
                    scope_context=scope_context,
                )
                await method(request, headers={"X-Agent-Scope": "JWT-TEST"})

            elif build_request == "cross_trade_patterns":
                from tools.get_cross_trade_behavioral_patterns import GetCrossTradeBehavioralPatternsRequest
                request = GetCrossTradeBehavioralPatternsRequest(
                    account_id="acc-001",
                    window_days=30,
                    scope_context=scope_context,
                )
                await method(request, headers={"X-Agent-Scope": "JWT-TEST"})

            elif build_request == "weekly_summary":
                from tools.get_weekly_execution_summary import GetWeeklyExecutionSummaryRequest
                request = GetWeeklyExecutionSummaryRequest(
                    account_id="acc-001",
                    week_start=date(2026, 1, 6),
                    week_end=date(2026, 1, 12),
                    timezone="UTC",
                    scope_context=scope_context,
                )
                await method(request, headers={"X-Agent-Scope": "JWT-TEST"})

        except Exception as exc:
            # If headers were captured before any contract failure, that's fine.
            # Only fail if headers were never captured at all.
            if "headers" not in captured:
                raise AssertionError(
                    f"{class_name}.{method_name} did not forward headers to httpx "
                    f"(exception before HTTP call: {exc})"
                ) from exc

    assert captured.get("headers") is not None, (
        f"{class_name}.{method_name} did not forward headers to httpx"
    )
    assert captured["headers"].get("X-Agent-Scope") == "JWT-TEST", (
        f"{class_name}.{method_name}: X-Agent-Scope not forwarded; "
        f"got headers: {captured.get('headers')}"
    )
