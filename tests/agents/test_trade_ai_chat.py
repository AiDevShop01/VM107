"""
Wave 0 test scaffolding for VM107 trade AI chat handler.

Tests in this file are xfail stubs. Downstream plan 47-05 removes the
xfail markers when it implements the POST /api/v1/trades/{journal_id}/ai/chat
handler (ApiHandler subclass + X-API-KEY auth, validation, envelope persistence,
degraded flag).
"""
import pytest


@pytest.mark.xfail(reason="Wave 0 stub — implementation in 47-05")
def test_empty_message_422():
    """POST chat with empty message body returns 422."""
    raise AssertionError("not yet implemented")


@pytest.mark.xfail(reason="Wave 0 stub — implementation in 47-05")
def test_api_key_required():
    """POST chat without X-API-KEY header returns 401."""
    raise AssertionError("not yet implemented")


@pytest.mark.xfail(reason="Wave 0 stub — implementation in 47-05")
def test_journal_id_extracted_from_url():
    """Handler reads journal_id from request.view_args['journal_id'] and uses it in envelope persistence."""
    raise AssertionError("not yet implemented")


@pytest.mark.xfail(reason="Wave 0 stub — implementation in 47-05")
def test_success_envelope_persisted():
    """Successful chat persists exactly one envelope with journal_id, status='success', and writes input.message + output.response."""
    raise AssertionError("not yet implemented")


@pytest.mark.xfail(reason="Wave 0 stub — implementation in 47-05")
def test_failure_envelope_on_llm_error():
    """LLM chain exhaustion persists an envelope with status='failure' and returns 502 to caller."""
    raise AssertionError("not yet implemented")


@pytest.mark.xfail(reason="Wave 0 stub — implementation in 47-05")
def test_degraded_flag():
    """When failover fired (telemetry.fallback_used=True), response includes degraded=true and envelope status='degraded'."""
    raise AssertionError("not yet implemented")
