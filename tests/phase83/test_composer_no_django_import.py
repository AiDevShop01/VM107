"""REQ-83-D1b — IntelligenceFeedMacroComposer RISK-06 regression gate.

Phase 83 Plan 09: after the composer refactor, this file verifies that ALL
three forbidden cross-VM import patterns are absent from the composer source.

This is the CI regression gate — these tests must stay GREEN forever.

Pattern gates (per plan spec):
  - 'from VM100' in composer → FAIL (cross-VM package import)
  - 'from api.reference_data_models' in composer → FAIL (Django ORM model import)
  - 'from mission_control.services.analytics_calendar_service' in composer → FAIL (Django service)
"""
import pytest
from pathlib import Path

VM107_ROOT = Path(__file__).resolve().parents[2]
COMPOSER_PATH = VM107_ROOT / "emitters" / "intelligence_feed_macro_composer.py"


@pytest.mark.phase83
def test_no_vm100_cross_package_import():
    """intelligence_feed_macro_composer.py has no 'from VM100' import (RISK-06 gate)."""
    assert COMPOSER_PATH.exists(), f"Composer file not found: {COMPOSER_PATH}"
    source = COMPOSER_PATH.read_text()
    assert "from VM100" not in source, (
        "RISK-06 REGRESSION: 'from VM100' found in intelligence_feed_macro_composer.py. "
        "VM107 must never import from VM100 packages — use MacroCalendarHTTPClient instead."
    )


@pytest.mark.phase83
def test_no_django_reference_data_models_import():
    """intelligence_feed_macro_composer.py has no 'from api.reference_data_models' import."""
    assert COMPOSER_PATH.exists(), f"Composer file not found: {COMPOSER_PATH}"
    source = COMPOSER_PATH.read_text()
    assert "from api.reference_data_models" not in source, (
        "RISK-06 REGRESSION: 'from api.reference_data_models' found in composer. "
        "This is a VM100 Django ORM import — use HTTP client instead."
    )


@pytest.mark.phase83
def test_no_analytics_calendar_service_import():
    """intelligence_feed_macro_composer.py has no 'from mission_control.services.analytics_calendar_service' import."""
    assert COMPOSER_PATH.exists(), f"Composer file not found: {COMPOSER_PATH}"
    source = COMPOSER_PATH.read_text()
    assert "from mission_control.services.analytics_calendar_service" not in source, (
        "RISK-06 REGRESSION: 'from mission_control.services.analytics_calendar_service' found. "
        "This is a VM100 Django app service import — remove it, use HTTP client."
    )


@pytest.mark.phase83
def test_no_anthropic_direct_sdk():
    """intelligence_feed_macro_composer.py has no 'anthropic.Anthropic()' call (Pitfall 6 gate)."""
    assert COMPOSER_PATH.exists(), f"Composer file not found: {COMPOSER_PATH}"
    source = COMPOSER_PATH.read_text()
    assert "anthropic.Anthropic()" not in source, (
        "Pitfall 6 REGRESSION: 'anthropic.Anthropic()' found in composer. "
        "LLM calls must go through Phase 43 ModelRouter — never instantiate Anthropic() directly."
    )
