"""Deterministic ConfidenceVector computation per CTX-§9.

'Confidence is evidence telemetry, not LLM self-belief.'

The orchestrator (60-06) calls compute() AFTER writer output is sealed,
AFTER citation_validator.enforce() passes. Writer NEVER supplies this vector.

All 5 dimensions derive from the structured sentence array + resolved citation
metadata + replay resolution status + regime snapshot age. Identical inputs
yield identical output every call.

5 dimensions:
  citation_coverage        — fraction of ASSERTIONs with >= 1 citation
  source_diversity         — count of distinct registry_ids cited
  behavioral_evidence_density — evidence quality behind behavioral claims
  replay_completeness      — fraction of replay_line citations that resolved
  regime_data_freshness_hours — age of the regime snapshot (pass-through)
"""
from __future__ import annotations

import re
from pathlib import Path

from fingpt_core.contracts.narrative.envelope import NarrativeEnvelope
from fingpt_core.contracts.narrative.sentence import NarrativeSentence, SentenceClass
from fingpt_core.contracts.narrative.confidence import ConfidenceVector


# Heuristic regex to detect behavioral-claim sentences (Claude's Discretion rule,
# CONTEXT.md §9 line ~508).
# NOTE: Prefixes like "hesitat" match "hesitation", "hesitated", etc.
# We use \b only at the START (word boundary) and no trailing \b for prefix terms,
# since adding \b after "hesitat" would NOT match "hesitation" (word continues).
# Exact multi-word phrases ("late entry", "stop movement") use explicit \b at end.
BEHAVIORAL_CLAIM_PATTERN = re.compile(
    r"\bhesitat"
    r"|\brevenge\b"
    r"|\bfomo\b"
    r"|\bover.?manag"
    r"|\blate entry\b"
    r"|\bstop movement\b"
    r"|\bstop move\b",
    re.IGNORECASE,
)

# Registry IDs that count as "strong" (behavioral-specific) evidence.
# If a behavioral-claim ASSERTION cites one of these, it scores 1.0.
# Any other citation scores 0.5. No citation scores 0.0.
BEHAVIORAL_REGISTRY_IDS = frozenset({"behavioral_pattern", "behavioral_analysis_tool"})


class ConfidenceVectorCalculator:
    """Compute a deterministic ConfidenceVector from a sealed NarrativeEnvelope.

    Usage:
        calc = ConfidenceVectorCalculator()
        vector = calc.compute(envelope, replay_metadata, regime_snapshot_age_hours)

    No state is mutated; repeated calls with the same inputs return equal vectors.
    """

    def compute(
        self,
        envelope: NarrativeEnvelope,
        replay_metadata: dict[str, bool] | None = None,
        regime_snapshot_age_hours: float = 0.0,
    ) -> ConfidenceVector:
        """Compute the 5-dimensional ConfidenceVector.

        Args:
            envelope: The sealed NarrativeEnvelope produced by the writer.
            replay_metadata: Dict mapping replay_line citation keys
                (e.g. "replay_line:abc-123@frame_42") to bool (True = resolved).
                Absent keys default to False (not resolved).
            regime_snapshot_age_hours: Age in hours of the latest regime snapshot.

        Returns:
            A fully-populated ConfidenceVector (all fields in valid ranges).
        """
        replay_metadata = replay_metadata or {}

        assertions = [
            s for s in envelope.sentences
            if s.sentence_class == SentenceClass.ASSERTION
        ]
        cited_assertions = [s for s in assertions if s.citations]

        # ---- 1. citation_coverage -----------------------------------------------
        citation_coverage = len(cited_assertions) / max(1, len(assertions))

        # ---- 2. source_diversity — distinct registry_ids across ALL sentences ----
        distinct_ids: set[str] = set()
        for s in envelope.sentences:
            for c in s.citations:
                distinct_ids.add(c.registry_id)
        source_diversity = len(distinct_ids)

        # ---- 3. behavioral_evidence_density — Claude's Discretion rule ----------
        behavioral_scores: list[float] = []
        for s in assertions:
            if BEHAVIORAL_CLAIM_PATTERN.search(s.text):
                has_behavioral_cite = any(
                    c.registry_id in BEHAVIORAL_REGISTRY_IDS for c in s.citations
                )
                has_any_cite = bool(s.citations)
                if has_behavioral_cite:
                    behavioral_scores.append(1.0)
                elif has_any_cite:
                    behavioral_scores.append(0.5)
                else:
                    behavioral_scores.append(0.0)

        # No behavioral claims → trivially perfect (no risk to penalize)
        behavioral_evidence_density = (
            sum(behavioral_scores) / len(behavioral_scores)
            if behavioral_scores
            else 1.0
        )

        # ---- 4. replay_completeness — fraction of replay_line cites resolved ----
        replay_line_cites = [
            c
            for s in envelope.sentences
            for c in s.citations
            if c.registry_id == "replay_line"
        ]
        if replay_line_cites:
            resolved = 0
            for c in replay_line_cites:
                # Build lookup key matching the replay_metadata dict format.
                key = f"replay_line:{c.field}"
                if c.frame_anchor is not None:
                    key += f"@frame_{c.frame_anchor}"
                if replay_metadata.get(key, False):
                    resolved += 1
            replay_completeness = resolved / len(replay_line_cites)
        else:
            replay_completeness = 1.0  # no replay claims → trivially complete

        # ---- 5. regime_data_freshness_hours — pass-through ----------------------
        return ConfidenceVector(
            citation_coverage=round(citation_coverage, 4),
            source_diversity=source_diversity,
            behavioral_evidence_density=round(behavioral_evidence_density, 4),
            replay_completeness=round(replay_completeness, 4),
            regime_data_freshness_hours=regime_snapshot_age_hours,
        )
