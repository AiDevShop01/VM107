"""
Wave 0 test scaffolding for chat history reconstruction.

Tests in this file are xfail stubs. Downstream plan 47-05 removes the
xfail markers when it implements the history reconstruction logic
(ordering, failed envelope display, source_envelope_id chain).
"""
import pytest


@pytest.mark.xfail(reason="Wave 0 stub — implementation in 47-05")
def test_history_ordered():
    """History reconstruction returns envelopes ordered by timestamp ascending."""
    raise AssertionError("not yet implemented")


@pytest.mark.xfail(reason="Wave 0 stub — implementation in 47-05")
def test_history_includes_failures():
    """Envelopes with status='failure' appear in history with content '[Response failed — AI service error]' and failed: True."""
    raise AssertionError("not yet implemented")


@pytest.mark.xfail(reason="Wave 0 stub — implementation in 47-05")
def test_source_envelope_id_chain():
    """Chat envelopes have source_envelope_id set to the previous envelope's id in the same journal_id."""
    raise AssertionError("not yet implemented")
