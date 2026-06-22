"""Phase 89.1 Plan 01 follow-up fix (2026-06-22) — citation schema harmonization.

Regression tests for the contract gap discovered in 89.1-05 WAVE3-THRESHOLD-REPORT:

  VM107 returns citations as B1 CitationRef shape:
    {"citation_id": "c1", "source": "search_knowledge: FRED ...", "snippet": "..."}

  VM100 _parse_ask_response() expects Citation shape:
    {"ref_id": "c1", "kind": "indicator", "label": "..."}

  VM100 calls `Citation(**c)` which raises:
    TypeError: unexpected keyword argument 'citation_id'

  This caused ALL 20 UAT questions to return HTTP 500.

Fix: harmonize_citations() pure function in helpers/citation_harmonizer.py
maps B1 CitationRef dicts to VM100 Citation-compatible dicts before the
AskResponse envelope is returned from api_message.py.

See: .planning/phases/89.1-.../89.1-05-WAVE3-THRESHOLD-REPORT.md
"""
from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Import the harmonizer — will fail (RED phase) until the module is created.
# ---------------------------------------------------------------------------
from helpers.citation_harmonizer import harmonize_citations


# ---------------------------------------------------------------------------
# Fixtures: B1 CitationRef dicts (the shape VM107 currently emits)
# ---------------------------------------------------------------------------

B1_CITATION_SEARCH_KNOWLEDGE = {
    "citation_id": "c1",
    "source": "search_knowledge: FRED 'U.S. Consumer Price Index 2019-2024'",
    "snippet": "Board of Governors of the Federal Reserve System, CPI data...",
}

B1_CITATION_INDICATOR_HISTORY = {
    "citation_id": "c2",
    "source": "vm102.indicator_history",
    "snippet": "CPI 3.4%",
}

B1_CITATION_STRUCTURAL_EVENTS = {
    "citation_id": "c3",
    "source": "vm102.structural_events",
    "snippet": "Structural break detected Q1 2024",
}

B1_CITATION_REGIME_CURRENT = {
    "citation_id": "c4",
    "source": "vm102.regime_current",
    "snippet": "Current regime: risk-on",
}

B1_CITATION_UNKNOWN_SOURCE = {
    "citation_id": "c5",
    "source": "some_unknown_tool",
    "snippet": "Unknown tool output",
}

B1_CITATION_NO_SNIPPET = {
    "citation_id": "c6",
    "source": "search_knowledge: Qdrant semantic search",
    "snippet": None,
}

# Already-harmonized citation — must pass through unchanged (idempotent).
ALREADY_HARMONIZED = {
    "ref_id": "c7",
    "kind": "release",
    "label": "CPI March 2024 — BLS",
}


# ---------------------------------------------------------------------------
# Tests: harmonize_citations() must produce VM100-compatible Citation dicts
# ---------------------------------------------------------------------------


@pytest.mark.phase89_1
def test_harmonize_search_knowledge_maps_to_research_kind():
    """search_knowledge source → kind='research', ref_id=citation_id, label from snippet."""
    result = harmonize_citations([B1_CITATION_SEARCH_KNOWLEDGE])
    assert len(result) == 1
    c = result[0]
    assert c["ref_id"] == "c1", f"Expected ref_id='c1', got {c.get('ref_id')!r}"
    assert c["kind"] == "research", f"Expected kind='research' for search_knowledge, got {c.get('kind')!r}"
    assert "citation_id" not in c, "citation_id must NOT be present in harmonized output"
    assert "source" not in c, "source must NOT be present in harmonized output"
    assert "snippet" not in c, "snippet must NOT be present in harmonized output"


@pytest.mark.phase89_1
def test_harmonize_vm102_indicator_history_maps_to_indicator_kind():
    """vm102.indicator_history → kind='indicator'."""
    result = harmonize_citations([B1_CITATION_INDICATOR_HISTORY])
    assert result[0]["kind"] == "indicator"
    assert result[0]["ref_id"] == "c2"


@pytest.mark.phase89_1
def test_harmonize_vm102_structural_events_maps_to_episode_kind():
    """vm102.structural_events → kind='episode'."""
    result = harmonize_citations([B1_CITATION_STRUCTURAL_EVENTS])
    assert result[0]["kind"] == "episode"
    assert result[0]["ref_id"] == "c3"


@pytest.mark.phase89_1
def test_harmonize_vm102_regime_maps_to_episode_kind():
    """vm102.regime_current → kind='episode'."""
    result = harmonize_citations([B1_CITATION_REGIME_CURRENT])
    assert result[0]["kind"] == "episode"
    assert result[0]["ref_id"] == "c4"


@pytest.mark.phase89_1
def test_harmonize_unknown_source_falls_back_to_research():
    """Unrecognised source prefix → kind='research' (safe fallback, not dropped)."""
    result = harmonize_citations([B1_CITATION_UNKNOWN_SOURCE])
    assert result[0]["kind"] == "research"
    assert result[0]["ref_id"] == "c5"


@pytest.mark.phase89_1
def test_harmonize_no_snippet_produces_label_from_source():
    """When snippet is None, label is derived from the source string."""
    result = harmonize_citations([B1_CITATION_NO_SNIPPET])
    c = result[0]
    assert c.get("label") is not None, "label must not be None when snippet is absent"
    assert len(c["label"]) <= 120, f"label must be <=120 chars, got {len(c['label'])}"


@pytest.mark.phase89_1
def test_harmonize_label_is_truncated_to_120_chars():
    """Long snippet is truncated to <=120 characters."""
    long_citation = {
        "citation_id": "cLong",
        "source": "search_knowledge: FRED",
        "snippet": "A" * 200,
    }
    result = harmonize_citations([long_citation])
    assert len(result[0]["label"]) <= 120


@pytest.mark.phase89_1
def test_harmonize_already_harmonized_passthrough():
    """Dicts that already have ref_id/kind are passed through unchanged (idempotent)."""
    result = harmonize_citations([ALREADY_HARMONIZED])
    c = result[0]
    assert c["ref_id"] == "c7"
    assert c["kind"] == "release"
    assert c["label"] == "CPI March 2024 — BLS"


@pytest.mark.phase89_1
def test_harmonize_empty_list_returns_empty():
    """Empty input list → empty output list."""
    assert harmonize_citations([]) == []


@pytest.mark.phase89_1
def test_harmonize_mixed_list_all_produce_ref_id():
    """Mixed B1 and already-harmonized citations all produce ref_id output."""
    mixed = [
        B1_CITATION_SEARCH_KNOWLEDGE,
        ALREADY_HARMONIZED,
        B1_CITATION_INDICATOR_HISTORY,
    ]
    result = harmonize_citations(mixed)
    assert len(result) == 3
    for c in result:
        assert "ref_id" in c, f"Expected ref_id in {c!r}"
        assert "citation_id" not in c, f"citation_id must not be in {c!r}"
        assert "kind" in c, f"Expected kind in {c!r}"


@pytest.mark.phase89_1
def test_vm100_citation_schema_accepts_research_kind():
    """VM100 Citation schema must accept kind='research' (schema extension check).

    This test imports the Citation schema from vm100 serializers via a path
    check — since we cannot import the Django app directly from this test,
    we read the serializers.py source and assert 'research' appears in the
    allowed kinds documentation or the schema has no explicit enum restriction.

    If VM100 Citation uses Literal['indicator'|'episode'|'release'|'edge'],
    this test will fail and the schema must be extended.
    """
    import pathlib

    vm100_serializers = pathlib.Path(
        "/Volumes/ HardDrive/FinGPT/VM100/backend/api/macro/serializers.py"
    )
    source = vm100_serializers.read_text()

    # The Citation.kind field must NOT use a Literal type that excludes 'research'.
    # It should be `kind: str` or `kind: Literal[..., "research"]`.
    # If the field is `kind: str`, it accepts any string — pass.
    # If it's `kind: Literal[...]`, it must include 'research'.

    import re
    # Find the Citation class definition
    citation_class_match = re.search(
        r"class Citation\(Schema\):(.*?)(?=\nclass |\Z)", source, re.DOTALL
    )
    assert citation_class_match, "Citation class not found in serializers.py"
    citation_body = citation_class_match.group(1)

    # Check if kind is restricted to a Literal without 'research'
    if "Literal" in citation_body and "kind" in citation_body:
        # If Literal is used for kind, 'research' must be included
        assert '"research"' in citation_body or "'research'" in citation_body, (
            "VM100 Citation.kind uses Literal but does not include 'research'. "
            "Either change `kind: str` to not use Literal, or add 'research' to the Literal. "
            "VM107 search_knowledge citations map to kind='research'."
        )
    # If kind is `str`, any value is accepted — test passes implicitly.
