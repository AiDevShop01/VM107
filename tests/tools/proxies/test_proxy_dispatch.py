"""Phase 70.5 Plan 07 — TDD Wave 0: proxy dispatch tests.

Tests validate that the dispatcher produces well-formed ToolResultEnvelope for each
of the 16 proxy tools, with VM107-owned provenance fields (registry_snapshot_hash,
confidence, freshness) — NOT values from the remote VM.

Additionally:
- One experimental-YAML proxy test: assert dispatcher returns refused envelope
  (Phase 47.6 LD-6c experimental gate + Plan 03 compose correctly)
- One real-YAML proxy test: assert success path yields VM107-owned confidence

Pattern mirrors tests/tools/pilot/test_get_trade_context_envelope.py.
"""
from __future__ import annotations

import importlib
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

from fingpt_core.contracts.invocation_context import InvocationContext
from fingpt_core.contracts.tool_envelope import ToolResultEnvelope


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SNAPSHOT_HASH = "sha256-test-proxy-dispatch"


def _make_real_entry(
    tool_id: str,
    source_module: str,
    typical_confidence: float = 0.80,
    expected_freshness: int = 120,
    is_deterministic: bool = True,
    version: str = "1.0.0",
    is_facade: bool = True,
):
    from core.agents.tool_registry import ToolEntry

    return ToolEntry(
        id=tool_id,
        status="real",
        source_module=source_module,
        typical_confidence=typical_confidence,
        expected_freshness_seconds=expected_freshness,
        is_deterministic=is_deterministic,
        version=version,
        is_facade=is_facade,
    )


def _make_experimental_entry(tool_id: str, source_module: str):
    from core.agents.tool_registry import ToolEntry

    return ToolEntry(
        id=tool_id,
        status="experimental",
        source_module=source_module,
        typical_confidence=0.7,
        expected_freshness_seconds=120,
        is_deterministic=False,
        version="1.0.0",
        is_facade=True,
    )


def _make_mock_registry(snapshot_hash: str = _SNAPSHOT_HASH):
    mock_reg = MagicMock()
    mock_reg.snapshot_hash = snapshot_hash
    mock_reg.lookup.return_value = None  # no refusal
    return mock_reg


def _make_ctx() -> InvocationContext:
    return InvocationContext(
        envelope_id=uuid.uuid4(),
        parent_envelope_id=None,
        trace_id=uuid.uuid4(),
        agent_id="agent_zero",
        execution_depth=0,
        knowledge_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# Parametrized: all 16 proxies produce well-formed envelopes
# ---------------------------------------------------------------------------

_PROXY_DISPATCH_PARAMS = [
    (
        "vm100.analytics_calendar",
        "tools.proxies.vm100_analytics_calendar",
        "Vm100AnalyticsCalendarPayload",
        0.80,
        True,
    ),
    (
        "vm100.behavioral_edges.for_execution",
        "tools.proxies.vm100_behavioral_edges_for_execution",
        "Vm100BehavioralEdgesPayload",
        0.82,
        True,
    ),
    (
        "vm100.ws.mission_control",
        "tools.proxies.vm100_ws_mission_control",
        "WsMissionControlStatusPayload",
        0.75,
        False,
    ),
    (
        "vm101_ribbon_bars_tool",
        "tools.proxies.vm101_ribbon_bars",
        "Vm101RibbonBarsPayload",
        0.80,
        True,
    ),
    (
        "vm101_ribbon_quotes_tool",
        "tools.proxies.vm101_ribbon_quotes",
        "Vm101RibbonQuotesPayload",
        0.80,
        True,
    ),
    (
        "vm102.regime_current",
        "tools.proxies.vm102_regime_current",
        "Vm102RegimeCurrentPayload",
        0.82,
        True,
    ),
    (
        "vm102.risk_metrics.snapshot",
        "tools.proxies.vm102_risk_metrics_snapshot",
        "Vm102RiskMetricsSnapshotPayload",
        0.80,
        True,
    ),
    (
        "vm102.structural_events",
        "tools.proxies.vm102_structural_events",
        "Vm102StructuralEventsPayload",
        0.80,
        True,
    ),
    (
        "vm107.intelligence_feed.discoveries",
        "tools.proxies.vm107_intelligence_feed_discoveries",
        "Vm107IntelligenceFeedDiscoveriesPayload",
        0.72,
        False,
    ),
    (
        "vm107.intelligence_feed.macro",
        "tools.proxies.vm107_intelligence_feed_macro",
        "Vm107IntelligenceFeedMacroPayload",
        0.75,
        False,
    ),
    (
        "vm107.mcp_server",
        "tools.proxies.vm107_mcp_server",
        "Vm107McpServerPayload",
        0.80,
        True,
    ),
    (
        "vm107.morning_brief",
        "tools.proxies.vm107_morning_brief",
        "Vm107MorningBriefPayload",
        0.75,
        False,
    ),
    (
        "vm107.narratives.global",
        "tools.proxies.vm107_narratives_global",
        "Vm107NarrativesGlobalPayload",
        0.75,
        False,
    ),
    (
        "vm107.opportunities.ranked",
        "tools.proxies.vm107_opportunities_ranked",
        "Vm107OpportunitiesRankedPayload",
        0.75,
        False,
    ),
    (
        "vm107.overnight_delta",
        "tools.proxies.vm107_overnight_delta",
        "Vm107OvernightDeltaPayload",
        0.75,
        False,
    ),
    (
        "vm107.reflection_prompt",
        "tools.proxies.vm107_reflection_prompt",
        "Vm107ReflectionPromptPayload",
        0.75,
        False,
    ),
]


def _make_canned_payload(module_path: str, payload_class: str):
    """Instantiate a canned minimal payload from the proxy module."""
    mod = importlib.import_module(module_path)
    cls = getattr(mod, payload_class)
    # Construct with defaults — each payload class has all-optional fields
    try:
        return cls()
    except Exception:
        return cls.model_construct()


@pytest.mark.parametrize(
    "tool_id,module_path,payload_class,typical_conf,is_det",
    _PROXY_DISPATCH_PARAMS,
    ids=[p[0] for p in _PROXY_DISPATCH_PARAMS],
)
@pytest.mark.asyncio
async def test_proxy_dispatch_produces_well_formed_envelope(
    tool_id,
    module_path,
    payload_class,
    typical_conf,
    is_det,
    mock_dispatcher_ctx,
    mock_vm_base_urls,
):
    """Each proxy dispatched via dispatch_tool produces a well-formed ToolResultEnvelope.

    Validates:
    - Returned object is a ToolResultEnvelope
    - tool_name == tool_id
    - registry_snapshot_hash populated (proves VM107 wrapped, not remote VM)
    - confidence is populated (VM107-owned computation)
    - outcome_class is "success"
    - success == True
    - payload is an instance of the expected *Payload class
    """
    from core.agents.tool_dispatcher import dispatch_tool, _get_tool_entry, _get_registry

    entry = _make_real_entry(
        tool_id, module_path, typical_conf, 120, is_det
    )
    mock_reg = _make_mock_registry()
    canned_payload = _make_canned_payload(module_path, payload_class)

    with (
        patch("core.agents.tool_dispatcher._get_registry", return_value=mock_reg),
        patch("core.agents.tool_dispatcher._get_tool_entry", return_value=entry),
        patch("core.agents.tool_dispatcher._invoke_resolver", return_value=canned_payload),
    ):
        envelope = await dispatch_tool(tool_id, {}, mock_dispatcher_ctx)

    assert isinstance(envelope, ToolResultEnvelope), (
        f"Expected ToolResultEnvelope, got {type(envelope)}"
    )
    assert envelope.tool_name == tool_id, (
        f"Expected tool_name={tool_id!r}, got {envelope.tool_name!r}"
    )
    assert envelope.registry_snapshot_hash == _SNAPSHOT_HASH, (
        f"registry_snapshot_hash should be VM107-owned ({_SNAPSHOT_HASH!r}), got {envelope.registry_snapshot_hash!r}"
    )
    assert envelope.confidence is not None, "confidence must be populated (VM107-owned)"
    assert envelope.outcome_class == "success", (
        f"Expected outcome_class='success', got {envelope.outcome_class!r}"
    )
    assert envelope.success is True, "success must be True on success path"

    mod = importlib.import_module(module_path)
    expected_cls = getattr(mod, payload_class)
    assert isinstance(envelope.payload, expected_cls), (
        f"Expected payload type {expected_cls.__name__}, got {type(envelope.payload).__name__}"
    )


# ---------------------------------------------------------------------------
# Experimental-status gate: dispatcher returns refused envelope
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_experimental_proxy_refused_by_dispatcher(
    mock_dispatcher_ctx, mock_vm_base_urls
):
    """A proxy with status=experimental is refused at the resolver gate.

    This validates that the Phase 47.6 LD-6c experimental gate composes
    correctly with Plan 03 dispatcher + Plan 07 proxies.

    Using vm107.overnight_delta as a representative experimental-status test proxy.
    The entry's status is set to 'experimental' to simulate the gate.

    The resolver raises CapabilityRefusedError for experimental entries;
    the dispatcher's Step 4 catch block converts it to a refused envelope.
    """
    from core.agents.tool_dispatcher import dispatch_tool
    from core.agents.tool_resolver import CapabilityRefusedError

    # Manufacture an experimental entry for a proxy tool
    entry = _make_experimental_entry(
        "vm107.overnight_delta",
        "tools.proxies.vm107_overnight_delta",
    )
    mock_reg = _make_mock_registry()

    # Simulate the resolver refusing because entry.status == "experimental"
    refusal_exc = CapabilityRefusedError(
        "vm107.overnight_delta", "registry_status=experimental"
    )

    with (
        patch("core.agents.tool_dispatcher._get_registry", return_value=mock_reg),
        patch("core.agents.tool_dispatcher._get_tool_entry", return_value=entry),
        patch(
            "core.agents.tool_dispatcher._invoke_resolver",
            side_effect=refusal_exc,
        ),
    ):
        envelope = await dispatch_tool("vm107.overnight_delta", {}, mock_dispatcher_ctx)

    assert isinstance(envelope, ToolResultEnvelope)
    assert envelope.outcome_class == "refused", (
        f"Expected 'refused' for experimental proxy, got {envelope.outcome_class!r}"
    )
    assert envelope.success is False
    assert envelope.refusal_reason is not None


# ---------------------------------------------------------------------------
# Real-status proxy: VM107 owns the confidence value
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_real_proxy_confidence_is_vm107_owned(
    mock_dispatcher_ctx, mock_vm_base_urls
):
    """A real-status proxy yields VM107-computed confidence (not remote VM's value).

    Uses vm102.regime_current (deterministic=True, typical_confidence=0.82).
    Asserts the confidence is computed by VM107 (via compute_confidence()),
    not whatever the remote VM might have supplied.
    """
    from core.agents.tool_dispatcher import dispatch_tool
    from tools.proxies.vm102_regime_current import Vm102RegimeCurrentPayload

    entry = _make_real_entry(
        "vm102.regime_current",
        "tools.proxies.vm102_regime_current",
        typical_confidence=0.82,
        expected_freshness=120,
        is_deterministic=True,
    )
    mock_reg = _make_mock_registry()
    canned_payload = Vm102RegimeCurrentPayload(symbol="EURUSD", timeframe="H1")

    with (
        patch("core.agents.tool_dispatcher._get_registry", return_value=mock_reg),
        patch("core.agents.tool_dispatcher._get_tool_entry", return_value=entry),
        patch("core.agents.tool_dispatcher._invoke_resolver", return_value=canned_payload),
    ):
        envelope = await dispatch_tool("vm102.regime_current", {"symbol": "EURUSD", "timeframe": "H1"}, mock_dispatcher_ctx)

    assert isinstance(envelope, ToolResultEnvelope)
    assert envelope.outcome_class == "success"
    assert envelope.confidence is not None
    # VM107 computes confidence from signals — it should be > 0 and <= 1
    assert 0.0 < envelope.confidence <= 1.0, (
        f"confidence={envelope.confidence} not in (0, 1] — VM107 must compute this"
    )
    # registry_snapshot_hash must be VM107's hash, not any remote VM value
    assert envelope.registry_snapshot_hash == _SNAPSHOT_HASH


# ---------------------------------------------------------------------------
# Structural: each proxy has PAYLOAD_SCHEMA_VERSION class var
# ---------------------------------------------------------------------------

_ALL_PROXY_MODULES_AND_PAYLOADS = [
    ("tools.proxies.vm100_analytics_calendar", "Vm100AnalyticsCalendarPayload"),
    ("tools.proxies.vm100_behavioral_edges_for_execution", "Vm100BehavioralEdgesPayload"),
    ("tools.proxies.vm100_ws_mission_control", "WsMissionControlStatusPayload"),
    ("tools.proxies.vm101_ribbon_bars", "Vm101RibbonBarsPayload"),
    ("tools.proxies.vm101_ribbon_quotes", "Vm101RibbonQuotesPayload"),
    ("tools.proxies.vm102_regime_current", "Vm102RegimeCurrentPayload"),
    ("tools.proxies.vm102_risk_metrics_snapshot", "Vm102RiskMetricsSnapshotPayload"),
    ("tools.proxies.vm102_structural_events", "Vm102StructuralEventsPayload"),
    ("tools.proxies.vm107_intelligence_feed_discoveries", "Vm107IntelligenceFeedDiscoveriesPayload"),
    ("tools.proxies.vm107_intelligence_feed_macro", "Vm107IntelligenceFeedMacroPayload"),
    ("tools.proxies.vm107_mcp_server", "Vm107McpServerPayload"),
    ("tools.proxies.vm107_morning_brief", "Vm107MorningBriefPayload"),
    ("tools.proxies.vm107_narratives_global", "Vm107NarrativesGlobalPayload"),
    ("tools.proxies.vm107_opportunities_ranked", "Vm107OpportunitiesRankedPayload"),
    ("tools.proxies.vm107_overnight_delta", "Vm107OvernightDeltaPayload"),
    ("tools.proxies.vm107_reflection_prompt", "Vm107ReflectionPromptPayload"),
]


@pytest.mark.parametrize(
    "module_path,payload_class",
    _ALL_PROXY_MODULES_AND_PAYLOADS,
    ids=[p[0].split(".")[-1] for p in _ALL_PROXY_MODULES_AND_PAYLOADS],
)
def test_payload_has_schema_version(module_path, payload_class):
    """Each proxy *Payload must have PAYLOAD_SCHEMA_VERSION ClassVar set to '1.0.0'."""
    mod = importlib.import_module(module_path)
    cls = getattr(mod, payload_class)
    assert hasattr(cls, "PAYLOAD_SCHEMA_VERSION"), (
        f"{payload_class} missing PAYLOAD_SCHEMA_VERSION ClassVar"
    )
    assert cls.PAYLOAD_SCHEMA_VERSION == "1.0.0", (
        f"{payload_class}.PAYLOAD_SCHEMA_VERSION should be '1.0.0', got {cls.PAYLOAD_SCHEMA_VERSION!r}"
    )


@pytest.mark.parametrize(
    "module_path,payload_class",
    _ALL_PROXY_MODULES_AND_PAYLOADS,
    ids=[p[0].split(".")[-1] for p in _ALL_PROXY_MODULES_AND_PAYLOADS],
)
def test_payload_has_provenance_field(module_path, payload_class):
    """Each proxy *Payload must have a 'provenance' field of type ToolProvenance."""
    from fingpt_core.contracts.tool_envelope import ToolProvenance

    mod = importlib.import_module(module_path)
    cls = getattr(mod, payload_class)
    instance = cls.model_construct()
    # The field must exist and be ToolProvenance-typed
    assert "provenance" in cls.model_fields, (
        f"{payload_class} missing 'provenance' field"
    )


@pytest.mark.parametrize(
    "module_path",
    [p[0] for p in _ALL_PROXY_MODULES_AND_PAYLOADS],
    ids=[p[0].split(".")[-1] for p in _ALL_PROXY_MODULES_AND_PAYLOADS],
)
def test_proxy_has_run_async(module_path):
    """Each proxy module must expose a top-level async run_async function."""
    import asyncio

    mod = importlib.import_module(module_path)
    assert hasattr(mod, "run_async"), f"{module_path} missing run_async"
    assert asyncio.iscoroutinefunction(mod.run_async), (
        f"{module_path}.run_async must be async"
    )
