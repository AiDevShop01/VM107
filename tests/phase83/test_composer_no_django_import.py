"""REQ-83-D1b — IntelligenceFeedMacroComposer must NOT import Django models.

Wave 4 Plan 09 will GREEN this test.

Pitfall 7 (from CONTEXT.md): The existing composer (if it exists in a legacy location)
may have 'from api.reference_data_models import ...' or 'from mission_control.services ...'
imports that tie VM107 to the VM100 Django ORM. This is a no-cross-VM-ORM violation.

The new Phase 83 composer lives in VM107/emitters/ and must be Django-free.
"""
import pytest
from pathlib import Path

VM107_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.phase83
def test_no_django_reference_data_models_import():
    """intelligence_feed_macro_composer.py does not import from api.reference_data_models.

    REQ-83-D1b, Pitfall 7: 'from api.reference_data_models import' in VM107 code
    means VM107 is importing VM100 Django ORM models directly — a cross-VM ORM violation.
    """
    composer_file = VM107_ROOT / "emitters" / "intelligence_feed_macro_composer.py"
    if not composer_file.exists():
        pytest.fail("RED skeleton — Wave 4 Plan 09 will GREEN this (file doesn't exist yet)")

    source = composer_file.read_text()
    assert "from api.reference_data_models import" not in source, (
        "REQ-83-D1b FAIL: 'from api.reference_data_models import' found in composer. "
        "Remove cross-VM Django ORM import — use HTTP client instead."
    )
    pytest.fail("RED skeleton — Wave 4 Plan 09 will GREEN this")


@pytest.mark.phase83
def test_no_mission_control_services_import():
    """intelligence_feed_macro_composer.py does not import from mission_control.services.

    REQ-83-D1b, Pitfall 7: mission_control.services is a VM100 Django app.
    VM107 must not import from it directly.
    """
    composer_file = VM107_ROOT / "emitters" / "intelligence_feed_macro_composer.py"
    if not composer_file.exists():
        pytest.fail("RED skeleton — Wave 4 Plan 09 will GREEN this (file doesn't exist yet)")

    source = composer_file.read_text()
    assert "from mission_control.services" not in source, (
        "REQ-83-D1b FAIL: 'from mission_control.services' found in composer. "
        "Remove cross-VM Django service import — use HTTP client instead."
    )
    pytest.fail("RED skeleton — Wave 4 Plan 09 will GREEN this")


@pytest.mark.phase83
def test_no_django_import_anywhere_in_composer():
    """intelligence_feed_macro_composer.py does not import Django at all.

    REQ-83-D1b: VM107 emitters are Django-free by design. Any 'import django' or
    'from django.' in an emitter file is an architectural violation.
    """
    composer_file = VM107_ROOT / "emitters" / "intelligence_feed_macro_composer.py"
    if not composer_file.exists():
        pytest.fail("RED skeleton — Wave 4 Plan 09 will GREEN this (file doesn't exist yet)")

    source = composer_file.read_text()
    for forbidden in ("import django", "from django."):
        assert forbidden not in source, (
            f"REQ-83-D1b FAIL: '{forbidden}' found in intelligence_feed_macro_composer.py. "
            "VM107 emitters must not import Django — use HTTP clients for VM100 data."
        )
    pytest.fail("RED skeleton — Wave 4 Plan 09 will GREEN this")
