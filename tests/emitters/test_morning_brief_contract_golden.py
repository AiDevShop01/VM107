"""Golden-fixture round-trip test for MorningBriefContract.

The fixture documents the EXPECTED wire shape consumed by Plan 09's VM100
PRE state briefing namespace + downstream UI. Any change to the contract
breaks this test, surfacing the cross-VM impact loudly.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from emitters.contracts.morning_brief import MorningBriefContract


pytestmark = pytest.mark.phase_67


_FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "golden"
    / "morning_brief"
    / "sample.json"
)


def test_morning_brief_golden_fixture_round_trips():
    """sample.json deserializes → contract → serializes back byte-stable."""
    raw = _FIXTURE_PATH.read_text(encoding="utf-8")
    data = json.loads(raw)

    contract = MorningBriefContract.model_validate(data)
    # Use by_alias=True so leading-underscore alias `_demo` is preserved.
    rebuilt = contract.model_dump(mode="json", by_alias=True)

    # Compare semantically (dict eq) not textually (whitespace tolerance).
    assert rebuilt == data, (
        "Golden fixture round-trip mismatch — contract shape changed without "
        "fixture update. Update sample.json AND notify Plan 09 / VM100 client owners."
    )


def test_morning_brief_golden_fixture_all_required_fields():
    """Golden must exercise EVERY required field on the contract."""
    data = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    required = {
        "brief_id",
        "account_id",
        "generated_at",
        "headline",
        "body",
        "top_catalysts",
        "risk_alerts",
        "confidence_score",
        "confidence_tier",
        "missing_sources",
        "_demo",
        "novelty_score",
        "novelty_crossed",
    }
    missing = required - set(data.keys())
    assert not missing, f"Golden fixture missing required fields: {missing}"
