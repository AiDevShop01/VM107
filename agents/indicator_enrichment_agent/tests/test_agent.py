"""Phase 88.1 Plan 08 — TDD RED scaffold for IndicatorEnrichmentAgent.

Tests lock:
  (1) agent.invoke returns valid IndicatorEnrichment for fixture LLM output.
  (2) Pydantic validation failure -> 1 retry; second failure -> raises.
  (3) raw_text in LLM output is stripped and validation passes (if other fields valid).
  (4) Over-token output triggers a second attempt.
  (5) Curator YAML loads and parses correctly.

Write-time Pydantic gate: IndicatorEnrichment.model_validate() is called on every
LLM call; agents retries once on ValidationError per Phase 38 pattern.
"""
import json
import sys
import os
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

# Resolve fingpt_core so we can import the Pydantic contract.
# In production VM107 this is installed as a package; in dev test we sys.path it.
_DAGSTER_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', '..', '..', 'Dagster')
)
_FINGPT_CORE = os.path.join(_DAGSTER_ROOT, 'fingpt_core', 'src')
if _FINGPT_CORE not in sys.path:
    sys.path.insert(0, _FINGPT_CORE)

from fingpt_core.contracts.indicator_enrichment import IndicatorEnrichment, TOKEN_BUDGET_HARD, TOKEN_BUDGET_SOFT


# ── Shared test fixtures ────────────────────────────────────────────────────

CURATOR_LAYER = {
    'indicator_id': 'CPIAUCSL',
    'name': 'Consumer Price Index for All Urban Consumers',
    'category': 'inflation',
    'frequency': 'monthly',
    'country': 'US',
    'importance': 'critical',
    'short_description': 'Headline US consumer price inflation',
    'why_it_matters': 'Primary policy lever for the Fed.',
    'affected_assets': ['DEXUSEU', 'DGS10', 'SP500'],
}

# A valid LLM JSON response (no raw_text — contract forbids it)
VALID_LLM_JSON = json.dumps({
    'current_narrative': 'CPI remains above 2% target with sticky core services components.',
    'trading_implications': 'Higher-for-longer Fed posture pressures long-duration bonds.',
    'recent_changes': 'March 2026 print 3.2% YoY, slightly above 3.1% consensus.',
    'confidence': 0.85,
})

# An LLM response that wraps content in raw_text (the forbidden field)
RAW_TEXT_LLM_JSON = json.dumps({
    'raw_text': json.dumps({
        'current_narrative': 'CPI remains above target.',
        'trading_implications': 'Bonds under pressure.',
        'recent_changes': 'Latest print beat consensus.',
        'confidence': 0.80,
    })
})

# An LLM response that is invalid JSON
INVALID_JSON = 'this is not json'

# An LLM response with oversized narrative (exceeds TOKEN_BUDGET_HARD * 4 chars)
OVERSIZE_LLM_JSON = json.dumps({
    'current_narrative': 'X' * (TOKEN_BUDGET_HARD * 5),
    'trading_implications': 'Bonds under pressure.',
    'recent_changes': 'Latest print beat consensus.',
    'confidence': 0.80,
})

NORMAL_FOLLOWUP_JSON = json.dumps({
    'current_narrative': 'CPI concise narrative.',
    'trading_implications': 'Bonds under pressure.',
    'recent_changes': 'Latest print beat consensus.',
    'confidence': 0.80,
})


def _make_agent(llm_response: str | list[str]):
    """Build an IndicatorEnrichmentAgent with a mock LLM client.

    If llm_response is a list, the mock returns items in sequence.
    """
    from agents.indicator_enrichment_agent.agent import IndicatorEnrichmentAgent
    agent = IndicatorEnrichmentAgent()
    mock_client = MagicMock()
    if isinstance(llm_response, list):
        mock_client.complete.side_effect = llm_response
    else:
        mock_client.complete.return_value = llm_response
    agent.llm_client = mock_client
    return agent


# ── Test (1): Valid response returns IndicatorEnrichment ───────────────────

def test_invoke_valid_response_returns_enrichment():
    """Agent returns a validated IndicatorEnrichment on first-attempt success."""
    agent = _make_agent(VALID_LLM_JSON)
    result = agent.invoke('CPIAUCSL', CURATOR_LAYER)
    assert isinstance(result, IndicatorEnrichment)
    assert result.indicator_id == 'CPIAUCSL'
    assert 'CPI' in result.current_narrative
    assert result.confidence == pytest.approx(0.85)
    assert result.version == 1
    assert result.model is not None
    assert result.prompt_version is not None


# ── Test (2): Validation failure -> 1 retry -> raises on second failure ────

def test_invoke_validation_failure_retries_once_then_raises():
    """Two consecutive invalid JSON responses: agent retries once, then raises."""
    agent = _make_agent([INVALID_JSON, INVALID_JSON])
    with pytest.raises(Exception):
        agent.invoke('CPIAUCSL', CURATOR_LAYER)
    # Exactly 2 calls to llm_client.complete (initial + 1 retry)
    assert agent.llm_client.complete.call_count == 2


# ── Test (3): raw_text in LLM output is stripped before validation ──────────

def test_invoke_strips_raw_text_field_before_validation():
    """LLM that emits raw_text: agent strips it; if other fields valid, succeeds."""
    # The VALID_LLM_JSON is returned on second attempt after raw_text is stripped
    # For this test we construct a payload with raw_text alongside valid fields
    mixed_json = json.dumps({
        'raw_text': 'forbidden content',
        'current_narrative': 'CPI above target.',
        'trading_implications': 'Bonds weaken.',
        'recent_changes': 'Beat consensus.',
        'confidence': 0.75,
    })
    agent = _make_agent(mixed_json)
    # After stripping raw_text, the remaining fields are valid — should succeed
    result = agent.invoke('CPIAUCSL', CURATOR_LAYER)
    assert isinstance(result, IndicatorEnrichment)
    assert result.indicator_id == 'CPIAUCSL'


# ── Test (3b): raw_text ONLY (no valid fields) -> validation fails -> retry -> raises ──

def test_invoke_raw_text_only_raises_after_retry():
    """LLM returns raw_text-wrapped content with no direct fields: strips raw_text,
    remaining dict has no required IndicatorEnrichment fields -> ValidationError -> retry."""
    agent = _make_agent([RAW_TEXT_LLM_JSON, RAW_TEXT_LLM_JSON])
    with pytest.raises(Exception):
        agent.invoke('CPIAUCSL', CURATOR_LAYER)
    assert agent.llm_client.complete.call_count == 2


# ── Test (4): Over-token output triggers retry ──────────────────────────────

def test_invoke_oversize_narrative_triggers_retry():
    """Narrative exceeding hard token budget (chars proxy) triggers retry.
    Second attempt returns valid normal-size output → success."""
    agent = _make_agent([OVERSIZE_LLM_JSON, NORMAL_FOLLOWUP_JSON])
    result = agent.invoke('CPIAUCSL', CURATOR_LAYER)
    # Should succeed on second attempt
    assert isinstance(result, IndicatorEnrichment)
    assert len(result.current_narrative) <= TOKEN_BUDGET_HARD
    # Two calls: first (oversize) failed budget check, second succeeded
    assert agent.llm_client.complete.call_count == 2


# ── Test (5): Curator YAML loads and parses correctly ──────────────────────

def _curator_yaml_path(indicator_id: str) -> str:
    """Resolve the absolute path to a curator YAML from the test directory.

    Directory depth from __file__:
      VM107/agents/indicator_enrichment_agent/tests/test_agent.py
      ->  3 parent steps up to reach VM107/:
          tests/ -> indicator_enrichment_agent/ -> agents/ -> VM107/
    Curator YAMLs are at VM107/config/curator/indicators/
    """
    vm107_root = os.path.normpath(
        os.path.join(os.path.dirname(__file__), '..', '..', '..')
    )
    return os.path.join(vm107_root, 'config', 'curator', 'indicators', f'{indicator_id}.yaml')


def test_curator_yaml_cpiaucsl_parses():
    """CPIAUCSL.yaml loads with all required keys."""
    import yaml
    yaml_path = _curator_yaml_path('CPIAUCSL')
    assert os.path.exists(yaml_path), f'YAML not found: {yaml_path}'
    with open(yaml_path) as f:
        data = yaml.safe_load(f)
    for key in ('indicator_id', 'name', 'category', 'frequency', 'country', 'importance',
                'short_description', 'why_it_matters', 'affected_assets'):
        assert key in data, f'Missing required key: {key}'
    assert data['indicator_id'] == 'CPIAUCSL'
    assert isinstance(data['affected_assets'], list)


def test_curator_yaml_payems_parses():
    """PAYEMS.yaml loads with all required keys."""
    import yaml
    yaml_path = _curator_yaml_path('PAYEMS')
    assert os.path.exists(yaml_path), f'YAML not found: {yaml_path}'
    with open(yaml_path) as f:
        data = yaml.safe_load(f)
    assert data['indicator_id'] == 'PAYEMS'
    assert 'importance' in data


def test_curator_yaml_fedfunds_parses():
    """FEDFUNDS.yaml loads with all required keys."""
    import yaml
    yaml_path = _curator_yaml_path('FEDFUNDS')
    assert os.path.exists(yaml_path), f'YAML not found: {yaml_path}'
    with open(yaml_path) as f:
        data = yaml.safe_load(f)
    assert data['indicator_id'] == 'FEDFUNDS'
    assert 'importance' in data
