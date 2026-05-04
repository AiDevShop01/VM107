"""
Wave 0 test scaffolding for envelope_writer journal_id persistence.

Tests in this file are xfail stubs. Downstream plan 47-02 removes the
xfail marker when it extends build_envelope/write_envelope to accept
and persist the journal_id kwarg.
"""
import pytest


@pytest.mark.xfail(reason="Wave 0 stub — implementation in 47-02")
def test_write_with_journal_id():
    """build_envelope accepts journal_id kwarg and write_envelope persists it."""
    # Test will instantiate build_envelope(..., journal_id="j1"), write to a fake db,
    # assert insert call includes journal_id="j1"
    raise AssertionError("not yet implemented")
