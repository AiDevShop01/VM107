"""Conftest for tests/agents/ — mirrors tests/routing/conftest.py path setup.

Phase 44 additions:
- mock_agent_context: minimal AgentContext-like stub for Agent Zero DI
- mock_mongo_client: in-memory dict double exposing db["agent_envelopes"]
- valid_hypothesis: Hypothesis fixture used by invocation + tool-scope tests
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# VM107 root is grandparent of this conftest (tests/agents/conftest.py -> tests/agents -> tests -> VM107)
_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

from core.contracts.schemas import Hypothesis


@pytest.fixture
def mock_agent_context():
    """
    Minimal AgentContext-like stub for Agent Zero dependency injection.

    Provides get_data/set_data simulation using an internal dict, plus
    agent_name and config.profile attributes used by tool scope checks.
    """
    ctx = MagicMock()
    ctx._data = {}
    ctx.agent_name = "A0"
    ctx.config = MagicMock()
    ctx.config.profile = "agent0"
    ctx.get_data.side_effect = lambda k, d=None: ctx._data.get(k, d)
    ctx.set_data.side_effect = lambda k, v: ctx._data.update({k: v})
    return ctx


@pytest.fixture
def mock_mongo_client():
    """
    In-memory MongoDB double exposing db["agent_envelopes"].

    Backed by a plain list so tests can assert on inserted documents without
    a real MongoDB connection. insert_one() appends to inserted_docs.
    find() returns an iterator over inserted_docs (no filter support).
    """
    inserted_docs: list = []

    col = MagicMock()
    col.inserted_docs = inserted_docs
    col.insert_one.side_effect = lambda doc: inserted_docs.append(doc)
    col.find.return_value = iter(inserted_docs)

    db = MagicMock()
    db.__getitem__ = MagicMock(side_effect=lambda name: col if name == "agent_envelopes" else MagicMock())
    return db


@pytest.fixture
def valid_hypothesis():
    """Minimal valid Hypothesis for use in invocation and tool-scope tests."""
    return Hypothesis(
        hypothesis="momentum tends to persist in trending markets",
        variables=["rsi_14", "ema_20"],
        confidence=0.7,
    )


# ================================================================
# PHASE 47.1 ADDITIONS — Wave 0 evaluation runner fixtures
# ================================================================

@pytest.fixture
def mock_evaluation_llm():
    """AsyncMock factory for the evaluation LLM call.

    Returns an AsyncMock configured to return a canned valid JSON string
    matching the PreTradeEvaluation schema on the first call.

    To parametrise for retry-once-then-fail tests:
        mock_evaluation_llm.side_effect = [PlainTextResult_instance, valid_json_str]

    Usage in tests:
        with patch("core.agents.evaluation_runner._call_llm_structured",
                   new=mock_evaluation_llm):
            result = await run_pre_trade_evaluation(...)
    """
    import json as _json

    canned_valid_json = _json.dumps({
        "recommendation": "enter",
        "confidence": 0.82,
        "score": 74,
        "max_score": 100,
        "direction": "long",
        "instrument": "XAUUSD",
        "check_results": {
            "htf_alignment": "pass",
            "compression_pause": "pass",
            "displacement_candle": "unclear",
            "location_quality": "pass",
            "rr_acceptable": "pass",
        },
        "reasoning_summary": "Strong HTF alignment with clean displacement. Location quality confirmed.",
        "risks": ["Upcoming NFP data could reverse momentum", "Spread widening near session open"],
        "invalidations": ["Price closes below 2618 structure low", "HTF bearish shift confirmed"],
        "next_action": "Enter at 2625 limit, SL 2612, TP 2645. Risk 1%.",
    })

    mock = AsyncMock(return_value=canned_valid_json)
    return mock


@pytest.fixture
def mock_eval_db():
    """MagicMock MongoDB double for evaluation runner tests.

    Exposes db["agent_envelopes"] with find(), find_one(), insert_one() configured.

    Backed by an in-memory list so tests can assert on call args without a
    real MongoDB connection. Compatible with the mock_mongo_client pattern
    (Phase 44) but extended for evaluation history queries.

    Usage:
        with patch("core.agents.evaluation_runner.get_mongo_db",
                   return_value=mock_eval_db):
            result = await run_pre_trade_evaluation(...)
        # Assert history was queried:
        mock_eval_db["agent_envelopes"].find.assert_called_once_with(...)
    """
    history_docs: list = []
    inserted_docs: list = []

    envelopes_col = MagicMock()
    envelopes_col.find.return_value = iter(history_docs)
    envelopes_col.find_one.return_value = None
    envelopes_col.insert_one.side_effect = lambda doc: inserted_docs.append(doc)
    envelopes_col._history_docs = history_docs
    envelopes_col._inserted_docs = inserted_docs

    db = MagicMock()
    db.__getitem__ = MagicMock(
        side_effect=lambda name: envelopes_col if name == "agent_envelopes" else MagicMock()
    )
    return db


# ================================================================
# PHASE 172-01 ADDITIONS — shared Wave-0 subscriber-wiring harness
# ================================================================
#
# Every downstream subscriber-wiring plan (SC-1 / SC-2 / SC-4 in 172-04 / 172-05)
# drives the same synthetic MACRO_RELEASE through `subscriber.handle` and then
# through `assemble() -> assess() -> run_panel()`. Rather than let each test
# hand-roll its own EconomicEvent + fake readers (drift-prone, and easy to get
# the immutable knowledge_time wrong — Phase 168 D-06a look-ahead pitfall), the
# three fixtures below centralise that harness:
#
#   * macro_release_event  — a valid, frozen MACRO_RELEASE EconomicEvent carrying
#                            a FIXED, immutable, PAST, tz-aware knowledge_time
#                            (never wall-clock now()).
#   * stub_domain_fetcher  — the Callable[[str, EconomicEvent], Any] the
#                            subscriber injects: a lightweight Domain stand-in for
#                            "growth", None for unknown slugs (mirrors the real
#                            DomainSnapshotFetcher transient-miss -> None contract).
#   * stub_facet_deps      — a FacetDeps whose domain_state_reader returns a
#                            populated {"status":"ok",...} envelope so assemble()
#                            yields a NON-empty pack with a real state_version
#                            (not the "unavailable" sentinel that makes assess()
#                            abstain -> SC-1 "real claims" fails silently).
#
# All three are import-light (no network clients constructed) and module-scope
# friendly so downstream plans can parametrise them.

from datetime import datetime, timezone

from contracts.economic_intelligence.events import (
    EconomicEvent,
    EventSeverity,
    EventType,
)
from core.evidence.assembler import FacetDeps

# The synthetic event's immutable as-of. FIXED in the past + tz-aware UTC so a
# test can assert it is NOT wall-clock now() — the whole point of the 168 D-06a
# no-re-stamp guarantee is that this value flows through the fan-out verbatim.
MACRO_RELEASE_KNOWLEDGE_TIME = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

# The single domain slug the synthetic event affects (one of the canonical 12).
MACRO_RELEASE_SLUG = "growth"


class _DomainStandin:
    """Lightweight Domain stand-in the subscriber's ``analyst.invoke`` accepts.

    The subscriber only passes the fetched object straight into
    ``analyst.invoke(domain, {...})`` — for the Wave-0 harness a real
    (heavy, ``extra='forbid'``) ``Domain`` is unnecessary; a stand-in carrying
    the ``slug`` is enough for the wiring tests to inject. Downstream plans that
    need a real ``Domain`` can override this fixture.
    """

    def __init__(self, slug: str) -> None:
        self.slug = slug

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<_DomainStandin slug={self.slug!r}>"


class _StubDomainStateReader:
    """Fake VM102-backed ``domain_state_reader`` for ``FacetDeps``.

    Exposes the typed ``get_domain_state(country, domain_slug, *,
    knowledge_time=None, previous=False)`` seam consumed by the REQUIRED
    ``domain_state`` composer (core/evidence/facets/domain_state.py:88). Returns
    a populated ``status="ok"`` envelope carrying a real ``state_version`` so the
    assembled pack is NON-empty (``state_version`` is not the ``"unavailable"``
    sentinel) and ``assess()`` produces real claims instead of abstaining.

    Records every call on ``.calls`` so downstream tests can assert the
    country/slug/knowledge_time actually threaded through.
    """

    def __init__(self, state_version: str = "US:growth:v1") -> None:
        self.state_version = state_version
        self.calls: list[dict] = []

    def get_domain_state(
        self, country, domain_slug, *, knowledge_time=None, previous=False
    ):
        self.calls.append(
            {
                "country": country,
                "domain_slug": domain_slug,
                "knowledge_time": knowledge_time,
                "previous": previous,
            }
        )
        return {
            "status": "ok",
            "data": {
                "current": {
                    "label": "Expanding",
                    "score": 0.35,
                    "confidence": 0.8,
                    "state_version": self.state_version,
                },
                "previous": {
                    "label": "Stable",
                    "score": 0.10,
                    "confidence": 0.8,
                    "state_version": "US:growth:v0",
                },
            },
            "meta": {
                "state_version": self.state_version,
                "previous_state_version": "US:growth:v0",
                "knowledge_time": None,
                "latest_only": True,
                "as_of_honored": True,
                "reason": None,
            },
        }


@pytest.fixture
def macro_release_event() -> EconomicEvent:
    """A valid, frozen MACRO_RELEASE event with an immutable PAST knowledge_time.

    ``payload.affected_domains`` intersects the canonical 12 (``growth``) so the
    subscriber dispatches; ``knowledge_time`` is the fixed past tz-aware
    ``MACRO_RELEASE_KNOWLEDGE_TIME`` (asserted != now() by consumers).
    """
    return EconomicEvent(
        event_id="evt-172-macro-growth-0001",
        event_type=EventType.MACRO_RELEASE,
        severity=EventSeverity.HIGH,
        country="US",
        occurred_at=MACRO_RELEASE_KNOWLEDGE_TIME,
        source="vm101.economic_event",
        payload={
            "affected_domains": [MACRO_RELEASE_SLUG],
            "snapshot_version": "gs_2024_01_15",
        },
        knowledge_time=MACRO_RELEASE_KNOWLEDGE_TIME,
    )


@pytest.fixture
def stub_domain_fetcher():
    """A ``Callable[[str, EconomicEvent], Any]`` for the subscriber's fetcher seam.

    Returns a lightweight ``Domain`` stand-in for ``"growth"`` and ``None`` for
    any unknown slug — mirroring the real ``DomainSnapshotFetcher`` contract
    (transient miss / unknown slug -> ``None``).
    """

    def _fetch(slug: str, event: EconomicEvent):
        if slug == MACRO_RELEASE_SLUG:
            return _DomainStandin(slug)
        return None

    return _fetch


@pytest.fixture
def stub_facet_deps() -> FacetDeps:
    """A ``FacetDeps`` whose ``domain_state_reader`` yields a NON-empty pack.

    Only the REQUIRED ``domain_state_reader`` is supplied (populated
    ``status="ok"`` envelope with a real ``state_version``); the ENRICHMENT
    readers stay ``None`` and degrade honest-empty. This is enough for
    ``assemble()`` to produce a pack whose ``state_version`` is a real version
    (not the ``"unavailable"`` sentinel) so ``assess()`` yields real claims.
    """
    return FacetDeps(domain_state_reader=_StubDomainStateReader())
