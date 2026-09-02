"""Phase 172 Plan 02 Task 3 (SC-3) — quant tool registration + budget proof.

Proves the SC-3 contract for the four L0-L4 progressive-disclosure quant tools
(``historical_percentile`` / ``change_point`` / ``surprise_score`` /
``lead_lag_correlation``):

1. Each tool is registered in the LIVE registry as a real, local-source tool that
   resolves to the reader-bound wrapper — ``dispatch_tool`` returns a
   ``ToolResultEnvelope`` with NO ``UnknownToolError`` (a genuinely unregistered id
   still raises, as a negative control).
2. The reader-bound wrappers BIND a concrete ``QuantReader`` (Pitfall 4): a caller
   never passes ``reader=``; an unwired reader fails LOUD, never fabricated.
3. ``dispatch`` honors ``max_tool_result_tokens`` — an over-cap payload yields
   ``outcome_class == "partial"`` via ``enforce_budget``; ``effective_cap`` resolves
   to ``min(tier cap, profile cap)``.

Hermetic: the VM102 quant substrate is reached through an injected fake
``QuantReader`` (set via ``quant_tool_dispatch.set_quant_reader``); the dispatcher's
registry/entry/resolver seams are patched. No network, no live registry boot.
"""
from __future__ import annotations

import importlib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from fingpt_core.contracts.invocation_context import InvocationContext
from fingpt_core.contracts.tool_envelope import ToolResultEnvelope

from core.agents.tool_registry import ToolEntry, _parse_source_module
from core.agents.tool_dispatcher import UnknownToolError, dispatch_tool
from core.evidence.tools import budget, quant_tools, quant_tool_dispatch


_TOOL_IDS = [
    "historical_percentile",
    "change_point",
    "surprise_score",
    "lead_lag_correlation",
]

# VM107/tests/tools/<this> -> parents[2] == VM107 root -> registry/tool
_YAML_DIR = Path(__file__).resolve().parents[2] / "registry" / "tool"
_EXPECTED_MODULE = "core.evidence.tools.quant_tool_dispatch"

# Positional args each wrapper takes (everything except the bound reader).
_TOOL_ARGS = {
    "historical_percentile": ("US_CORE_CPI",),
    "change_point": ("US_CORE_CPI",),
    "surprise_score": ("US_NFP_2026_08",),
    "lead_lag_correlation": ("US_CPI", "US_PPI"),
}


# ---------------------------------------------------------------------------
# Fixtures — fake typed reader + ctx + registry-entry-from-YAML
# ---------------------------------------------------------------------------


class _FakeReader:
    """Fake QuantReader (G10 seam) — deterministic rich scalar/struct reads."""

    def historical_percentile(self, series_id, *, knowledge_time=None):
        return quant_tools.PercentileRead(
            percentile=71.4,
            zscore=0.63,
            n_observations=180,
            window_start=datetime(2011, 1, 1, tzinfo=timezone.utc),
            window_end=datetime(2026, 1, 1, tzinfo=timezone.utc),
            distribution_summary={"p25": 40.0, "p50": 55.0, "p75": 68.0},
        )

    def change_point(self, series_id, *, knowledge_time=None):
        return quant_tools.ChangePointRead(
            change_point_count=2,
            last_change_index=142,
            last_change_at=datetime(2025, 12, 1, tzinfo=timezone.utc),
            recent_change=True,
            change_indices=(88, 142),
        )

    def surprise(self, event_id, *, knowledge_time=None):
        return quant_tools.SurpriseRead(
            category="MODERATE",
            standardized_surprise=1.4,
            raw_surprise=0.3,
            reaction_strength="ELEVATED",
        )

    def lead_lag(self, series_a, series_b, *, knowledge_time=None):
        return quant_tools.CorrelationRead(
            correlation=0.62,
            best_lag=3,
            best_lag_correlation=0.71,
            direction="a_leads_b",
        )


def _ctx() -> InvocationContext:
    return InvocationContext(
        envelope_id=uuid.uuid4(),
        parent_envelope_id=None,
        trace_id=uuid.uuid4(),
        agent_id="agent_zero",
        execution_depth=0,
        knowledge_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _entry_from_yaml(tool_id: str) -> ToolEntry:
    """Build a ToolEntry from the ACTUAL registry YAML (proves live registration).

    Reading the shipped YAML — rather than fabricating an entry — is what makes
    this a registration proof: the id, status, and location.source below are the
    real values the live registry loads.
    """
    raw = yaml.safe_load((_YAML_DIR / f"{tool_id}.yaml").read_text())
    return ToolEntry(
        id=raw["id"],
        status=raw["status"],
        source_module=_parse_source_module(raw["location"]["source"]),
        typical_confidence=raw["typical_confidence"],
        expected_freshness_seconds=raw["expected_freshness_seconds"],
        is_deterministic=raw["is_deterministic"],
        version=str(raw["version"]),
        is_facade=False,
    )


def _mock_registry(snapshot_hash: str = "sha-test-quant"):
    reg = MagicMock()
    reg.snapshot_hash = snapshot_hash
    reg.lookup.return_value = None  # no refusal path
    return reg


# ---------------------------------------------------------------------------
# 1. Registration — dispatch resolves each id, no UnknownToolError
# ---------------------------------------------------------------------------


def test_each_quant_tool_yaml_is_real_and_points_at_the_wrapper_module():
    """Every SC-3 YAML is a real, local-source tool resolving to the wrapper."""
    for tool_id in _TOOL_IDS:
        entry = _entry_from_yaml(tool_id)
        assert entry.id == tool_id
        assert entry.status == "real"
        assert entry.source_module == _EXPECTED_MODULE
        mod = importlib.import_module(entry.source_module)
        assert callable(getattr(mod, tool_id)), f"{tool_id} not exported by wrapper module"


@pytest.mark.parametrize("tool_id", _TOOL_IDS)
@pytest.mark.asyncio
async def test_dispatch_resolves_registered_quant_tool(tool_id):
    """dispatch_tool resolves each id and returns a ToolResultEnvelope (no UnknownToolError)."""
    entry = _entry_from_yaml(tool_id)
    canned = quant_tools.PercentilePayload(percentile=1.0)  # payload the resolver hands back
    with (
        patch("core.agents.tool_dispatcher._get_registry", return_value=_mock_registry()),
        patch("core.agents.tool_dispatcher._get_tool_entry", return_value=entry),
        patch("core.agents.tool_dispatcher._invoke_resolver", return_value=canned),
    ):
        env = await dispatch_tool(tool_id, {}, _ctx())

    assert isinstance(env, ToolResultEnvelope)  # never raised UnknownToolError
    assert env.tool_name == tool_id


@pytest.mark.asyncio
async def test_unregistered_id_still_raises_unknown_tool_error():
    """Negative control: a genuinely unregistered id raises UnknownToolError."""
    with (
        patch("core.agents.tool_dispatcher._get_registry", return_value=_mock_registry()),
        patch("core.agents.tool_dispatcher._get_tool_entry", side_effect=KeyError("nope")),
    ):
        with pytest.raises(UnknownToolError):
            await dispatch_tool("historical_percentile__NOT_REGISTERED", {}, _ctx())


# ---------------------------------------------------------------------------
# 2. Reader binding — Pitfall 4 closed structurally
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool_id", _TOOL_IDS)
def test_wrapper_takes_no_reader_kwarg(tool_id):
    """A caller need NOT pass reader= — the wrapper binds it internally."""
    import inspect

    sig = inspect.signature(getattr(quant_tool_dispatch, tool_id))
    assert "reader" not in sig.parameters


@pytest.mark.parametrize("tool_id", _TOOL_IDS)
def test_wrapper_binds_injected_reader(tool_id):
    """With a reader wired, the wrapper produces an envelope without reader=."""
    quant_tool_dispatch.set_quant_reader(_FakeReader())
    try:
        wrapper = getattr(quant_tool_dispatch, tool_id)
        env = wrapper(_ctx(), *_TOOL_ARGS[tool_id])
        assert isinstance(env, ToolResultEnvelope)
        assert env.tool_name == tool_id
    finally:
        quant_tool_dispatch.reset_quant_reader()


def test_unwired_reader_fails_loud_never_fabricates():
    """No wired reader -> QuantReaderNotConfigured (honest), never a fake read."""
    quant_tool_dispatch.reset_quant_reader()
    with pytest.raises(quant_tool_dispatch.QuantReaderNotConfigured):
        quant_tool_dispatch.historical_percentile(_ctx(), "US_CORE_CPI")


# ---------------------------------------------------------------------------
# 3. Budget — max_tool_result_tokens honored (over-cap -> partial)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool_id", _TOOL_IDS)
def test_over_cap_payload_marks_partial(tool_id):
    """A tiny profile cap forces outcome_class='partial' via enforce_budget."""
    quant_tool_dispatch.set_quant_reader(_FakeReader())
    try:
        wrapper = getattr(quant_tool_dispatch, tool_id)
        env = wrapper(
            _ctx(),
            *_TOOL_ARGS[tool_id],
            detail_level="RAW",
            profile_cap=1,  # 1 token cap — any real payload exceeds it
        )
        assert env.outcome_class == "partial", (
            f"{tool_id} over-cap payload must degrade visibly, not silently succeed"
        )
    finally:
        quant_tool_dispatch.reset_quant_reader()


@pytest.mark.asyncio
async def test_budget_partial_survives_the_dispatch_boundary():
    """Routing the wrapper through dispatch preserves the partial budget decision."""
    tool_id = "historical_percentile"
    entry = _entry_from_yaml(tool_id)
    quant_tool_dispatch.set_quant_reader(_FakeReader())

    async def _route(tid, kwargs, ctx):  # stand-in resolver -> the real wrapper
        return quant_tool_dispatch.historical_percentile(
            ctx, "US_CORE_CPI", detail_level="RAW", profile_cap=1
        )

    try:
        with (
            patch("core.agents.tool_dispatcher._get_registry", return_value=_mock_registry()),
            patch("core.agents.tool_dispatcher._get_tool_entry", return_value=entry),
            patch("core.agents.tool_dispatcher._invoke_resolver", side_effect=_route),
        ):
            env = await dispatch_tool(tool_id, {}, _ctx())
        assert isinstance(env, ToolResultEnvelope)
        # dispatch wraps the wrapper's envelope as payload; the budget decision the
        # wrapper made (outcome_class='partial') is carried through unchanged.
        assert env.payload.outcome_class == "partial"
    finally:
        quant_tool_dispatch.reset_quant_reader()


def test_effective_cap_is_min_of_tier_and_profile():
    """effective_cap = min(tier cap, profile max_tool_result_tokens)."""
    assert budget.effective_cap("COMPACT", 1000) == 250   # tier tighter
    assert budget.effective_cap("DETAILED", 100) == 100    # profile tighter
    assert budget.effective_cap("STANDARD", None) == 750   # no profile cap -> tier
    # and enforce_budget acts on it: a tiny profile cap on a real payload -> partial
    payload = quant_tools.PercentilePayload(percentile=71.4, zscore=0.63, n_observations=180)
    decision = budget.enforce_budget(payload, "STANDARD", profile_cap=1)
    assert decision.truncated is True
    assert decision.outcome_class == "partial"
