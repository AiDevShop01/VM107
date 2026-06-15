"""Phase 87 Wave 2 — Macro Transmission narration skill.

Constitutional skill bound to vm107.macro_transmission_analyst via the
``constitutional_skills`` field of its agent profile YAML. Owns:

  1. Prompt construction — hop-by-hop chain + episodic memory injection.
  2. LLM completion via Phase 43 router.
  3. Hard-assertion regex gate per agent profile YAML:
       - narrative_strength_for_3_hops:  >=3 matches of strength=N or strength:N
       - narrative_period:               >=1 ISO date range YYYY-MM-DD/YYYY-MM-DD
  4. Retry-once-degrade behaviour:
       - First attempt fails assertions → retry with corrective addendum
       - Second attempt also fails → raise NarrationFailedAfterRetry
       - Caller (agent.py) catches → emits degraded_fallback() Markdown
         and sets ``degraded=True`` on the envelope
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from tools.neo4j_macro_graph_walker import Hop


# Regex contract — must stay in sync with the agent profile YAML
# hard_assertions section. Patterns are duplicated here intentionally;
# the profile YAML is the source of truth for the contract, and these
# constants are the runtime implementation. A future PR may consolidate
# via a YAML-driven loader; for Wave 2 the duplication is deliberate.
STRENGTH_REGEX = r"strength\s*[=:]\s*-?\d"
PERIOD_REGEX = r"\d{4}-\d{2}-\d{2}/\d{4}-\d{2}-\d{2}"
STRENGTH_MIN_MATCHES = 3
PERIOD_MIN_MATCHES = 1


class NarrationFailedAfterRetry(Exception):
    """Raised when the LLM emits a narrative failing the regex gate twice."""


@dataclass
class TransmissionNarrationSkill:
    """Wraps LLM router + hard-assertion regex + retry/degrade contract."""

    llm_router: Any  # Phase 43 router; .complete(prompt: str) -> str
    strength_regex: str = STRENGTH_REGEX
    period_regex: str = PERIOD_REGEX
    strength_min_matches: int = STRENGTH_MIN_MATCHES
    period_min_matches: int = PERIOD_MIN_MATCHES

    # ---- public API ---------------------------------------------------

    def narrate(
        self,
        *,
        indicator_id: str,
        release: dict,
        chain: Iterable[Hop],
        episodes: Iterable[dict],
    ) -> tuple[str, bool]:
        """Produce a hop-by-hop narrative.

        Returns:
            (narrative_text, degraded)

            ``degraded`` is always ``False`` from this method — the agent
            sets it to ``True`` when ``NarrationFailedAfterRetry`` is
            raised and ``degraded_fallback`` is invoked.

        Raises:
            NarrationFailedAfterRetry: Both LLM attempts failed the regex.
        """
        chain_list = list(chain)
        episodes_list = list(episodes)
        prompt = self._build_prompt(indicator_id, release, chain_list, episodes_list)

        attempt_1 = self.llm_router.complete(prompt)
        if self._passes_assertions(attempt_1):
            return attempt_1, False

        retry_prompt = (
            prompt
            + "\n\nIMPORTANT RETRY INSTRUCTION:\n"
            + "Your previous response did not include the required inline "
            + "`strength=<value>` per hop and the `YYYY-MM-DD/YYYY-MM-DD` "
            + "evidence period. Rewrite the narrative ensuring every hop "
            + "names its strength + confidence + sample_size + period."
        )
        attempt_2 = self.llm_router.complete(retry_prompt)
        if self._passes_assertions(attempt_2):
            return attempt_2, False

        raise NarrationFailedAfterRetry(
            f"narrative failed hard assertions twice for {indicator_id}"
        )

    def degraded_fallback(self, chain: Iterable[Hop]) -> str:
        """Deterministic Markdown rendering — used when LLM degrades.

        The fallback STILL emits citation grammar [ref:edge:<src>:<dst>]
        and inline strength/confidence/n/period so downstream evidence
        drawer + Phase 71 citation resolver work even on the degraded path.
        """
        chain_list = list(chain)
        if not chain_list:
            return (
                "**Transmission chain (degraded — empty walk):**\n\n"
                "No edges returned from the macro graph for this indicator. "
                "Either the indicator is missing from the Wave 1 seed or the "
                "Neo4j walk returned zero results."
            )

        lines = ["**Transmission chain (degraded — narration unavailable):**", ""]
        for hop in chain_list:
            lines.append(
                f"- {hop.source} → {hop.target} "
                f"({hop.relationship_type}, "
                f"strength={hop.strength:.2f}, "
                f"confidence={hop.confidence:.2f}, "
                f"n={hop.sample_size}, "
                f"period={hop.evidence_period}) "
                f"[ref:edge:{hop.source}:{hop.target}]"
            )
        return "\n".join(lines)

    # ---- internals ----------------------------------------------------

    def _passes_assertions(self, text: str) -> bool:
        strength_hits = len(re.findall(self.strength_regex, text))
        period_hits = len(re.findall(self.period_regex, text))
        return (
            strength_hits >= self.strength_min_matches
            and period_hits >= self.period_min_matches
        )

    def _build_prompt(
        self,
        indicator_id: str,
        release: dict,
        chain: list[Hop],
        episodes: list[dict],
    ) -> str:
        chain_lines = "\n".join(
            f"- {h.source} → {h.target} ({h.relationship_type}): "
            f"strength={h.strength:.2f}, confidence={h.confidence:.2f}, "
            f"n={h.sample_size}, period={h.evidence_period}"
            for h in chain
        ) or "(no edges returned from the graph)"

        episode_lines = "\n".join(
            f"- [ref:episode:{e.get('memory_id', '?')}] {e.get('text', '')}"
            for e in episodes
        ) or "(no prior episodes)"

        actual = release.get("actual", "?")
        forecast = release.get("forecast", "?")
        surprise = release.get("surprise", "?")

        return (
            f"You are the macro_transmission_analyst. The {indicator_id} "
            f"indicator just released {actual} (forecast {forecast}, "
            f"surprise {surprise}).\n\n"
            f"Walk the causal chain hop-by-hop, one sentence per hop, "
            f"naming each strength + confidence + sample_size + evidence "
            f"period inline. Include [ref:edge:<src>:<dst>] citation "
            f"grammar for each hop.\n\n"
            f"Chain:\n{chain_lines}\n\n"
            f"Relevant prior episodes:\n{episode_lines}\n"
        )
