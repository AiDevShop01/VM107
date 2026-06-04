"""REQ-83-8 (VM107 side) — MacroCalendarClient calls VM100 /calendar/upcoming via HTTP.

Wave 4 Plan 09 will GREEN these tests by shipping:
  VM107/emitters/macro_calendar_client.py: MacroCalendarClient

The client must use HTTP (requests or httpx), NOT a Django ORM import.
This enforces the no-cross-VM-filesystem lock from MEMORY.md.
"""
import pytest
from unittest.mock import patch, MagicMock


@pytest.mark.phase83
def test_calendar_client_calls_vm100_endpoint():
    """MacroCalendarClient.get_upcoming_events() calls VM100 HTTP endpoint.

    REQ-83-8: The client must call GET /api/v1/mission-control/calendar/upcoming
    on the VM100 base URL (from MACRO_CALENDAR_BASE_URL env var per env-driven lock).
    No Django ORM. No filesystem reads. HTTP only.
    """
    from emitters.macro_calendar_client import MacroCalendarClient  # noqa: F401

    pytest.fail("RED skeleton — Wave 4 Plan 09 will GREEN this")


@pytest.mark.phase83
def test_calendar_client_uses_service_jwt():
    """MacroCalendarClient attaches Phase 65 service JWT in Authorization header.

    REQ-83-8: The VM100 /calendar/upcoming endpoint requires JWT auth (RISK-06).
    The client must read SERVICE_JWT_TOKEN from env and send it as Bearer token.
    """
    from emitters.macro_calendar_client import MacroCalendarClient  # noqa: F401

    pytest.fail("RED skeleton — Wave 4 Plan 09 will GREEN this")


@pytest.mark.phase83
def test_calendar_client_no_filesystem_read():
    """MacroCalendarClient does not read any filesystem on VM101 or VM100.

    MEMORY.md lock: Agents (VM107) must call typed VM APIs for data, never
    mount another VM's data lake or read ORM models directly.
    """
    import ast
    from pathlib import Path

    client_file = Path(__file__).resolve().parents[2] / "emitters" / "macro_calendar_client.py"
    if not client_file.exists():
        pytest.fail("RED skeleton — Wave 4 Plan 09 will GREEN this (file doesn't exist yet)")

    source = client_file.read_text()
    forbidden = ["open(", "Path(", "os.path", "django.db", "from api."]
    for pattern in forbidden:
        assert pattern not in source, (
            f"no-cross-VM-filesystem lock violated: '{pattern}' in macro_calendar_client.py"
        )
    pytest.fail("RED skeleton — Wave 4 Plan 09 will GREEN this")
