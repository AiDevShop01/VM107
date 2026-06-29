"""Phase 96 Wave 0 RED stub — REQ-96-8 find_countries_by_profile_query tool tests.

Plan 96-06 (Qdrant Cross-Country Search Tool) flips these to GREEN.

Tool contract (ContractTool, mirrors VM107/tools/qdrant/search_knowledge.py):
- Input: natural-language query string + optional filters (region, min_score)
- Output: top-K (default 10) country matches with similarity scores +
  matched-section excerpts (citation-ready per Phase 71 grammar)
- Backed by Qdrant `country_profiles` collection (2,712 points — RESEARCH §Open Q 2)
- Empty / zero-vector collection -> raises with operator-actionable message
  (NOT silent empty list — RESEARCH §Pitfall 3)
"""

from __future__ import annotations

import pytest


@pytest.mark.xfail(strict=False, reason="Wave 0 stub — Plan 96-06 flips to GREEN")
def test_find_countries_returns_top_k_for_canned_query():
    """REQ-96-8: 'high inflation emerging market' returns 10 country matches."""
    raise NotImplementedError("Plan 96-06: implement against REQ-96-8")


@pytest.mark.xfail(strict=False, reason="Wave 0 stub — Plan 96-06 flips to GREEN")
def test_find_countries_respects_region_filter():
    """REQ-96-8: region='asia' filter returns only Asian country ISOs."""
    raise NotImplementedError("Plan 96-06: implement against REQ-96-8 filter")


@pytest.mark.xfail(strict=False, reason="Wave 0 stub — Plan 96-06 flips to GREEN")
def test_find_countries_attaches_section_excerpts_as_citations():
    """REQ-96-8: each match carries the section text that scored it (Phase 71 grammar)."""
    raise NotImplementedError("Plan 96-06: implement against REQ-96-8 citations")


@pytest.mark.xfail(strict=False, reason="Wave 0 stub — Plan 96-06 flips to GREEN")
def test_find_countries_raises_operator_actionable_on_empty_collection():
    """REQ-96-8 + RESEARCH §Pitfall 3: zero-vector collection -> raise, not silent []."""
    raise NotImplementedError("Plan 96-06: implement against REQ-96-8 empty-handling")
