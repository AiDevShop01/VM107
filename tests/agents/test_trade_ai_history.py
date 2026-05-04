"""
Wave 0 test scaffolding for VM107 trade AI history handler.

Tests in this file are xfail stubs. Downstream plan 47-05 removes the
xfail markers when it implements the GET /api/v1/trades/{journal_id}/ai/history
handler.
"""
import pytest


@pytest.mark.xfail(reason="Wave 0 stub — implementation in 47-05")
def test_messages_ordered():
    """GET history returns messages in chronological order by timestamp."""
    raise AssertionError("not yet implemented")


@pytest.mark.xfail(reason="Wave 0 stub — implementation in 47-05")
def test_empty_for_new_journal():
    """GET history for a journal with no envelopes returns {messages: []}."""
    raise AssertionError("not yet implemented")
