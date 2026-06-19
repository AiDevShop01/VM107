"""Phase 88.1 Plan 09 — TDD tests for regenerate_indicator_enrichment mgmt command.

Tests lock:
  (1) Command succeeds for indicators where agent.invoke returns a valid envelope.
  (2) Command falls back (curator_fallback) for indicators where agent raises ValidationError.
  (3) Command is idempotent — --dry-run does not call _persist.
  (4) IRLTLT01EZM156N curator YAML uses canonical 'what_is_it' key (not the typo 'what_it_is').
  (5) All 5 new curator YAMLs (BUSLOANS, NONBORRES, PCEPI, TEDRATE, IRLTLT01EZM156N) load and parse.
  (6) Results dict: 4 success + 2 curator_fallback for mock scenario (4-valid / 2-raise).

Design: mock IndicatorEnrichmentAgent.invoke + Command._persist to avoid live API/DB calls.
"""
import os
import sys
import json
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from pydantic import ValidationError

# ── Path setup ────────────────────────────────────────────────────────────────
# Directory depth from __file__:
#   VM107/agents/indicator_enrichment_agent/management/commands/tests/test_regenerate.py
#   -> 5 parent steps to reach VM107/:
#      tests/ -> commands/ -> management/ -> indicator_enrichment_agent/ -> agents/ -> VM107/
_VM107_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', '..')
)
# Dagster root is a sibling of VM107 in the monorepo layout (/FinGPT/Dagster)
_DAGSTER_ROOT = os.path.normpath(os.path.join(_VM107_ROOT, '..', 'Dagster'))
_FINGPT_CORE = os.path.join(_DAGSTER_ROOT, 'fingpt_core', 'src')

for _path in [_VM107_ROOT, _FINGPT_CORE]:
    if _path not in sys.path:
        sys.path.insert(0, _path)

from fingpt_core.contracts.indicator_enrichment import IndicatorEnrichment


# ── Curator YAML helper ────────────────────────────────────────────────────────

def _curator_yaml_path(indicator_id: str) -> str:
    """Resolve path to a curator YAML from VM107 root."""
    return os.path.join(_VM107_ROOT, 'config', 'curator', 'indicators', f'{indicator_id}.yaml')


# ── Shared test fixture: valid IndicatorEnrichment instance ──────────────────

def _make_envelope(indicator_id: str) -> IndicatorEnrichment:
    """Build a minimal valid IndicatorEnrichment for the given indicator."""
    from datetime import datetime, timezone
    return IndicatorEnrichment(
        indicator_id=indicator_id,
        current_narrative=f'{indicator_id} is in focus.',
        trading_implications='Monitor closely.',
        recent_changes='No significant change.',
        confidence=0.80,
        generated_at=datetime.now(timezone.utc),
        version=1,
        model='claude-sonnet-x',
        prompt_version='88.1.0',
    )


# ── Command loader (avoids Django setup requirement) ─────────────────────────

def _load_command_module():
    """Import the mgmt command module without full Django stack."""
    import importlib.util
    cmd_path = os.path.join(
        _VM107_ROOT,
        'agents', 'indicator_enrichment_agent', 'management', 'commands',
        'regenerate_indicator_enrichment.py',
    )
    spec = importlib.util.spec_from_file_location('regenerate_indicator_enrichment', cmd_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['regenerate_indicator_enrichment'] = module
    spec.loader.exec_module(module)
    return module


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_command_module_importable():
    """The regenerate command module imports without error."""
    mod = _load_command_module()
    assert hasattr(mod, 'Command')
    assert hasattr(mod, 'TARGET_INDICATORS')


def test_target_indicators_set():
    """TARGET_INDICATORS contains exactly the 6-indicator target set."""
    mod = _load_command_module()
    expected = {'BUSLOANS', 'NONBORRES', 'PAYEMS', 'PCEPI', 'TEDRATE', 'IRLTLT01EZM156N'}
    assert set(mod.TARGET_INDICATORS) == expected


def test_command_dry_run_no_persist():
    """--dry-run: agent.invoke is called but _persist is NOT called."""
    mod = _load_command_module()
    cmd = mod.Command()
    cmd.stdout = MagicMock()
    cmd.stderr = MagicMock()
    cmd.stdout.write = MagicMock()
    cmd.stderr.write = MagicMock()
    cmd.style = MagicMock()
    cmd.style.SUCCESS = lambda s: s

    indicator = 'BUSLOANS'
    mock_envelope = _make_envelope(indicator)

    # Patch the IndicatorEnrichmentAgent on the loaded module object directly
    # (avoids sys.modules dotted-path resolution issues with spec_from_file_location).
    mock_agent_instance = MagicMock()
    mock_agent_instance.invoke.return_value = mock_envelope
    mock_agent_class = MagicMock(return_value=mock_agent_instance)

    original_class = mod.IndicatorEnrichmentAgent
    try:
        mod.IndicatorEnrichmentAgent = mock_agent_class

        with patch.object(cmd, '_persist') as mock_persist:
            cmd.handle(indicators=indicator, dry_run=True)

        # invoke was called (agent ran)
        mock_agent_instance.invoke.assert_called_once()
        # _persist was NOT called (dry-run)
        mock_persist.assert_not_called()
    finally:
        mod.IndicatorEnrichmentAgent = original_class


def test_command_success_calls_persist():
    """Non-dry-run: agent.invoke succeeds → _persist called."""
    mod = _load_command_module()
    cmd = mod.Command()
    cmd.stdout = MagicMock()
    cmd.stderr = MagicMock()
    cmd.stdout.write = MagicMock()
    cmd.stderr.write = MagicMock()
    cmd.style = MagicMock()
    cmd.style.SUCCESS = lambda s: s

    indicator = 'BUSLOANS'
    mock_envelope = _make_envelope(indicator)

    mock_agent_instance = MagicMock()
    mock_agent_instance.invoke.return_value = mock_envelope
    mock_agent_class = MagicMock(return_value=mock_agent_instance)

    original_class = mod.IndicatorEnrichmentAgent
    try:
        mod.IndicatorEnrichmentAgent = mock_agent_class

        with patch.object(cmd, '_persist') as mock_persist:
            cmd.handle(indicators=indicator, dry_run=False)

        mock_agent_instance.invoke.assert_called_once()
        mock_persist.assert_called_once_with(indicator, mock_envelope)
    finally:
        mod.IndicatorEnrichmentAgent = original_class


def test_command_validation_error_becomes_curator_fallback():
    """agent.invoke raises ValidationError → indicator goes into curator_fallback (not system_error)."""
    mod = _load_command_module()
    cmd = mod.Command()
    cmd.stdout = MagicMock()
    cmd.stderr = MagicMock()
    cmd.stdout.write = MagicMock()
    cmd.stderr.write = MagicMock()
    cmd.style = MagicMock()
    cmd.style.SUCCESS = lambda s: s

    indicator = 'BUSLOANS'

    def _raise_validation_error(*args, **kwargs):
        IndicatorEnrichment.model_validate({})

    mock_agent_instance = MagicMock()
    mock_agent_instance.invoke.side_effect = _raise_validation_error
    mock_agent_class = MagicMock(return_value=mock_agent_instance)

    original_class = mod.IndicatorEnrichmentAgent
    try:
        mod.IndicatorEnrichmentAgent = mock_agent_class

        with patch.object(cmd, '_persist') as mock_persist:
            cmd.handle(indicators=indicator, dry_run=True)

        # _persist never called
        mock_persist.assert_not_called()
        # stderr should have been written
        cmd.stderr.write.assert_called()
    finally:
        mod.IndicatorEnrichmentAgent = original_class


def test_command_four_success_two_fallback():
    """4 valid indicators + 2 raising indicators → results show 4 success + 2 curator_fallback."""
    mod = _load_command_module()
    cmd = mod.Command()
    cmd.stdout = MagicMock()
    cmd.stderr = MagicMock()
    cmd.stdout.write = MagicMock()
    cmd.stderr.write = MagicMock()
    cmd.style = MagicMock()
    cmd.style.SUCCESS = lambda s: s

    six_indicators = 'BUSLOANS,NONBORRES,PAYEMS,PCEPI,TEDRATE,IRLTLT01EZM156N'
    # TEDRATE and IRLTLT01EZM156N will raise
    raising = {'TEDRATE', 'IRLTLT01EZM156N'}

    def _invoke_side_effect(indicator_id, curator_layer):
        if indicator_id in raising:
            IndicatorEnrichment.model_validate({})
        return _make_envelope(indicator_id)

    mock_agent_instance = MagicMock()
    mock_agent_instance.invoke.side_effect = _invoke_side_effect
    mock_agent_class = MagicMock(return_value=mock_agent_instance)

    original_class = mod.IndicatorEnrichmentAgent
    try:
        mod.IndicatorEnrichmentAgent = mock_agent_class

        with patch.object(cmd, '_persist'):
            results = cmd.handle(indicators=six_indicators, dry_run=True)
    finally:
        mod.IndicatorEnrichmentAgent = original_class

    # 4 success, 2 curator_fallback, 0 system_error
    assert len(results['success']) == 4, f"Expected 4 success, got: {results['success']}"
    assert len(results['curator_fallback']) == 2, f"Expected 2 fallback, got: {results['curator_fallback']}"
    assert set(results['curator_fallback']) == raising
    assert len(results['system_error']) == 0


# ── Curator YAML correctness tests ───────────────────────────────────────────

CURATOR_YAML_IDS = ['BUSLOANS', 'NONBORRES', 'PCEPI', 'TEDRATE', 'IRLTLT01EZM156N']
REQUIRED_KEYS = ('indicator_id', 'name', 'category', 'frequency', 'country', 'importance',
                 'short_description', 'why_it_matters', 'affected_assets')


@pytest.mark.parametrize('indicator_id', CURATOR_YAML_IDS)
def test_curator_yaml_exists_and_parses(indicator_id):
    """Each new curator YAML loads with all required keys."""
    import yaml
    yaml_path = _curator_yaml_path(indicator_id)
    assert os.path.exists(yaml_path), f'Curator YAML not found: {yaml_path}'
    with open(yaml_path) as f:
        data = yaml.safe_load(f)
    for key in REQUIRED_KEYS:
        assert key in data, f'{indicator_id}.yaml missing required key: {key}'
    assert data['indicator_id'] == indicator_id
    assert isinstance(data['affected_assets'], list)
    assert len(data['affected_assets']) >= 1


def test_irltlt01ezm156n_yaml_uses_canonical_what_is_it_key():
    """IRLTLT01EZM156N.yaml must use 'what_is_it' (NOT the typo 'what_it_is')."""
    import yaml
    yaml_path = _curator_yaml_path('IRLTLT01EZM156N')
    assert os.path.exists(yaml_path), f'YAML not found: {yaml_path}'
    text = open(yaml_path).read()
    assert 'what_it_is' not in text, (
        "IRLTLT01EZM156N.yaml contains the typo 'what_it_is' — "
        "must use canonical key 'what_is_it'"
    )


def test_no_curator_yaml_uses_typo_key():
    """No curator YAML in the indicators dir uses the typo key 'what_it_is'."""
    import yaml
    curator_dir = os.path.join(_VM107_ROOT, 'config', 'curator', 'indicators')
    for fname in os.listdir(curator_dir):
        if not fname.endswith('.yaml'):
            continue
        text = open(os.path.join(curator_dir, fname)).read()
        assert 'what_it_is' not in text, (
            f'{fname} contains the typo key "what_it_is" — must use "what_is_it"'
        )
