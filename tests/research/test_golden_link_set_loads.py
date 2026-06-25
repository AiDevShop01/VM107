"""Phase 92 Plan 03 — sanity test that the 30-doc golden labelled set loads.

This is the ONE test that goes GREEN in the Wave 0 RED suite: it asserts the
fixtures exist, parse, count to 30, and reference only Phase-83-catalog FRED
IDs in their expected_indicators.
"""
from __future__ import annotations

import pytest


pytestmark = pytest.mark.phase92


def test_golden_set_has_exactly_30_docs(golden_link_set):
    assert len(golden_link_set) == 30, (
        f"Golden link set must have exactly 30 docs; got {len(golden_link_set)}"
    )


def test_golden_set_distribution_is_10_10_10(golden_link_set):
    by_source: dict[str, int] = {}
    for d in golden_link_set:
        by_source[d.source] = by_source.get(d.source, 0) + 1
    assert by_source == {"fomc": 10, "ecb": 10, "nber": 10}, (
        f"Distribution must be 10 FOMC + 10 ECB + 10 NBER; got {by_source}"
    )


def test_golden_set_tier_assignments(golden_link_set):
    """FOMC + ECB → tier 1; NBER → tier 3."""
    for d in golden_link_set:
        if d.source in ("fomc", "ecb"):
            assert d.expected_tier == 1, f"{d.doc_id} should be tier 1; got {d.expected_tier}"
        elif d.source == "nber":
            assert d.expected_tier == 3, f"{d.doc_id} should be tier 3; got {d.expected_tier}"
        else:
            pytest.fail(f"Unknown source {d.source} in {d.doc_id}")


def test_golden_set_expected_indicators_are_in_phase83_catalog(
    golden_link_set, mock_economic_indicator_catalog
):
    valid_ids = {e["id"] for e in mock_economic_indicator_catalog}
    for d in golden_link_set:
        for ind in d.expected_indicators:
            assert ind in valid_ids, (
                f"{d.doc_id} expects indicator {ind!r} which is NOT in the "
                f"Phase-83 catalog of 64 IDs."
            )


def test_golden_set_every_doc_has_at_least_one_expected_indicator(golden_link_set):
    """Pitfall 3 mitigation: every fixture must claim ≥1 indicator link.

    A doc with 0 expected indicators would be by-design unlinked — that's a
    legitimate case but should be a SEPARATE fixture, not part of the
    precision/recall harness. The harness expects ≥1 indicator per doc.
    """
    for d in golden_link_set:
        assert len(d.expected_indicators) >= 1, (
            f"{d.doc_id} has zero expected_indicators — should be in the "
            f"soft-reject test, not the precision/recall harness."
        )


def test_golden_set_text_files_are_substantive(golden_link_set):
    """Each fixture must have at least 300 chars of text — Stage 1 substring
    matching needs real prose, not a one-liner.
    """
    for d in golden_link_set:
        assert len(d.text) >= 300, (
            f"{d.doc_id} text is only {len(d.text)} chars; needs ≥300 for "
            f"meaningful synonym matching."
        )
