"""Phase 87 Plan 06 (Wave 3) — citation grammar test.

Asserts the narrative + supporting_evidence emitted by the regime analyst
conform to the Phase 71 evidence drawer grammar so Plan 87-12 (Wave 6
frontend) renders citations cleanly:

  - ``[ref:episode:<id>]``   — episodic memory (Wave 4 + later)
  - ``[ref:release:<id>]``   — Phase 86 historical analogue release
  - ``[ref:indicator:<id>]`` — anchor indicator reference

supporting_evidence entries must declare a ``kind`` in
``{analogue, anchor, episode}`` with required fields per kind. The test
constructs the regime analyst end-to-end so the assertions cover the
exact shapes the persistence layer writes — no canned-JSON drift.
"""
from __future__ import annotations

import re
import uuid
from unittest.mock import MagicMock

import pytest

from agents.macro_regime_analyst.agent import MacroRegimeAnalyst
from agents.macro_regime_analyst.historical_analogue_client import (
    HistoricalAnalogue,
)
from agents.macro_regime_analyst.skill_regime_narration import (
    RegimeNarrationSkill,
)

pytestmark = pytest.mark.phase_87


# Phase 71 evidence-drawer citation grammar — episode + release + indicator.
# Plan 87-12 (Wave 6 frontend) parses with this exact regex when rendering
# the narrative; the agent's narrative + degraded_fallback() MUST emit
# tokens this regex matches.
CITATION_RE = re.compile(
    r"\[ref:(?P<kind>episode|release|indicator):(?P<id>[A-Za-z0-9_-]+)\]"
)


# ---------------------------------------------------------------------------
# Static grammar tests — no agent wiring required
# ---------------------------------------------------------------------------


def test_well_formed_narrative_parses_cleanly():
    """Every ``[ref:`` token in a representative narrative is matched."""
    sample = (
        "The current regime is **stagflation**, marked by rising CPI "
        "[ref:indicator:CPIAUCSL], rising unemployment "
        "[ref:indicator:UNRATE], and contracting GDP "
        "[ref:indicator:GDP]. Comparable past releases: "
        "[ref:release:550e8400-e29b-41d4-a716-446655440000] "
        "[ref:release:550e8400-e29b-41d4-a716-446655440001] "
        "[ref:release:550e8400-e29b-41d4-a716-446655440002]. "
        "Earlier episode of the same regime: "
        "[ref:episode:ep-2022-stag-q1]."
    )
    matches = list(CITATION_RE.finditer(sample))
    assert sample.count("[ref:") == len(matches), (
        "every [ref: token must match the Phase 71 grammar; some did not"
    )
    kinds = {m.group("kind") for m in matches}
    assert "release" in kinds, "narrative MUST cite at least one release"
    assert "indicator" in kinds, "narrative MUST cite at least one anchor"


def test_malformed_citation_does_not_match():
    """Off-spec tokens (missing kind, bad chars) are rejected."""
    bad = "[ref::abc] [ref:release:] [ref:foo:bar] [ref:release:abc!]"
    matches = list(CITATION_RE.finditer(bad))
    # [ref:foo:bar] does NOT match (foo not a known kind);
    # [ref:release:abc!] does NOT match ('!' not in id charset);
    # both empty-id forms do NOT match.
    assert len(matches) == 0, (
        f"malformed tokens must not match grammar; got {matches!r}"
    )


# ---------------------------------------------------------------------------
# Agent-level test — verify supporting_evidence shape
# ---------------------------------------------------------------------------


def _build_agent_with_analogues(analogues: list[HistoricalAnalogue]):
    provider = MagicMock()
    provider.directions_at.return_value = (+1, +1, -1)
    analogue_client = MagicMock()
    analogue_client.find_analogues.return_value = analogues
    beliefs = MagicMock()
    beliefs.query.return_value = {"probability": 0.5, "confidence": 0.6}
    llm = MagicMock()
    citations_text = " ".join(
        f"[ref:release:{a.release_id}]" for a in analogues
    ) or "[ref:release:none]"
    llm.complete.return_value = (
        f"Stagflation regime persists; comparable to {citations_text}."
    )
    envelope_repo = MagicMock()
    envelope_repo.persist.return_value = uuid.uuid4()
    b1_repo = MagicMock()
    b1_repo.persist.return_value = uuid.uuid4()
    persist = MagicMock()
    persist.last_regime.return_value = "expansion"
    persist.create.return_value = uuid.uuid4()
    ws = MagicMock()
    return MacroRegimeAnalyst(
        anchor_direction_provider=provider,
        analogue_client=analogue_client,
        belief_store_client=beliefs,
        narration_skill=RegimeNarrationSkill(llm_router=llm),
        envelope_repo=envelope_repo,
        b1_repo=b1_repo,
        persist_repo=persist,
        ws_publisher=ws,
    )


def test_supporting_evidence_kinds_are_known(release_event_factory):
    """Every supporting_evidence row declares one of the known kinds."""
    analogues = [
        HistoricalAnalogue(
            release_id="rel-1",
            release_date="2022-03-10",
            indicator_id="CPIAUCSL",
            surprise=0.3,
            sample_size=180,
            evidence_period="2020-01-01/2025-01-01",
        ),
    ]
    agent = _build_agent_with_analogues(analogues)
    result = agent.run(release_event_factory())

    known_kinds = {"analogue", "anchor", "episode"}
    for row in result.supporting_evidence:
        assert row.get("kind") in known_kinds, (
            f"supporting_evidence row {row!r} has unknown kind"
        )


def test_supporting_evidence_required_fields_per_kind(release_event_factory):
    """Analogue rows + anchor rows have their required fields populated."""
    analogues = [
        HistoricalAnalogue(
            release_id="rel-9",
            release_date="2022-09-13",
            indicator_id="CPIAUCSL",
            surprise=0.4,
            sample_size=200,
            evidence_period="2018-01-01/2026-06-01",
        ),
    ]
    agent = _build_agent_with_analogues(analogues)
    result = agent.run(release_event_factory())

    for row in result.supporting_evidence:
        if row["kind"] == "analogue":
            for field in (
                "release_id", "release_date", "indicator_id",
                "sample_size", "evidence_period",
            ):
                assert field in row, (
                    f"analogue row {row!r} missing required field {field!r}"
                )
        elif row["kind"] == "anchor":
            for field in ("indicator_id", "direction"):
                assert field in row, (
                    f"anchor row {row!r} missing required field {field!r}"
                )
            assert row["direction"] in (-1, 0, 1), (
                f"anchor direction must be -1/0/1; got {row['direction']!r}"
            )


def test_emitted_narrative_satisfies_phase71_grammar(release_event_factory):
    """The narrative actually returned by the agent contains at least one
    Phase 71 ``[ref:release:<id>]`` token — this is the contract the
    Wave 6 frontend will rely on."""
    analogues = [
        HistoricalAnalogue(
            release_id="rel-xyz",
            release_date="2024-05-15",
            indicator_id="CPIAUCSL",
            surprise=0.5,
            sample_size=120,
            evidence_period="2020-01-01/2025-01-01",
        ),
    ]
    agent = _build_agent_with_analogues(analogues)
    result = agent.run(release_event_factory())

    matches = list(CITATION_RE.finditer(result.narrative_text))
    assert any(m.group("kind") == "release" for m in matches), (
        f"narrative must contain at least one [ref:release:<id>] token; "
        f"got {result.narrative_text!r}"
    )


def test_degraded_fallback_still_emits_citations(release_event_factory):
    """When narrate() fails, degraded_fallback() must still satisfy grammar."""
    from agents.macro_regime_analyst.skill_regime_narration import (
        RegimeNarrationSkill,
    )
    analogues = [
        HistoricalAnalogue(
            release_id="fallback-rel",
            release_date="2023-01-01",
            indicator_id="CPIAUCSL",
            surprise=0.2,
            sample_size=80,
            evidence_period="2019-01-01/2024-01-01",
        ),
    ]
    # LLM router that always returns garbage failing the gate
    llm = MagicMock()
    llm.complete.return_value = "this completion fails the gate"
    skill = RegimeNarrationSkill(llm_router=llm)
    fallback = skill.degraded_fallback(
        current_regime="stagflation",
        prior_regime="expansion",
        transition_probability=1.0,
        analogues=analogues,
    )
    matches = list(CITATION_RE.finditer(fallback))
    assert any(m.group("kind") == "release" for m in matches), (
        f"degraded_fallback() must still emit [ref:release:<id>] tokens; "
        f"got {fallback!r}"
    )
    # Names the regime explicitly so the frontend chip still renders.
    assert "stagflation" in fallback.lower()
