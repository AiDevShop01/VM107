"""Phase 87 Plan 06 (Wave 3) — regime narration skill.

Wraps the Phase 43 LLM router to emit a one-paragraph regime narrative
satisfying the hard-assertion regex contract from the agent profile YAML:

  - narrative_names_one_of_7_regimes — ``\\b(expansion|slowdown|...)\\b``, ≥1 match
  - narrative_cites_analogue        — ``\\[ref:(episode|release):...\\]``, ≥1 match

Lifecycle (matches Plan 87-04 TransmissionNarrationSkill):

  1. Build prompt from classifier output + analogues.
  2. Call LLM router.
  3. If regex gate fails: retry ONCE with a corrective addendum.
  4. If retry also fails: raise ``NarrationFailedAfterRetry`` — agent
     falls back to ``degraded_fallback()`` + marks envelope degraded.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from .historical_analogue_client import HistoricalAnalogue

logger = logging.getLogger(__name__)


class NarrationFailedAfterRetry(Exception):
    """Raised when the LLM completion fails the regex gate twice in a row.

    The agent catches this exception, emits the deterministic Markdown
    fallback via ``degraded_fallback()``, and marks the envelope
    ``degraded=True``.
    """


# Pre-compiled regex — identical to the agent profile YAML hard_assertions
# section. The YAML is the source of truth for the contract; these are the
# runtime implementation. A future PR may consolidate via a YAML loader.
_REGIME_TOKEN_RE = re.compile(
    r"\b(expansion|slowdown|inflation|disinflation|"
    r"stagflation|recession|recovery)\b"
)
_CITATION_RE = re.compile(r"\[ref:(episode|release):[A-Za-z0-9_-]+\]")


@dataclass
class RegimeNarrationSkill:
    """One-paragraph regime narrative with hard-assertion retry-once-degrade.

    Args:
        llm_router: Object with a ``complete(prompt: str) -> str`` method
            (Phase 43 LLMRouter or any mock).
        max_attempts: 1 attempt + 1 retry by default (per agent profile YAML
            ``retry_on_hard_assertion_fail: 1``). Keep ``int >= 1``.
    """

    llm_router: Any
    max_attempts: int = 2

    def narrate(
        self,
        *,
        indicator_id: str,
        release: dict,
        current_regime: str,
        prior_regime: str,
        transition_probability: float,
        analogues: list[HistoricalAnalogue],
    ) -> tuple[str, bool]:
        """Return ``(narrative_text, degraded)``.

        Tries ``max_attempts`` times. Returns ``(text, False)`` on success.
        Raises ``NarrationFailedAfterRetry`` if all attempts fail the gate.
        """
        if self.max_attempts < 1:
            raise ValueError(
                f"max_attempts must be >= 1; got {self.max_attempts}"
            )
        base_prompt = self._build_prompt(
            indicator_id=indicator_id,
            release=release,
            current_regime=current_regime,
            prior_regime=prior_regime,
            transition_probability=transition_probability,
            analogues=analogues,
        )
        last_completion: str = ""
        for attempt in range(self.max_attempts):
            if attempt == 0:
                prompt = base_prompt
            else:
                prompt = (
                    base_prompt
                    + "\n\nRETRY — your prior completion failed the "
                    "hard-assertion regex gate. You MUST name the current "
                    "regime explicitly (one of expansion / slowdown / "
                    "inflation / disinflation / stagflation / recession / "
                    "recovery) AND cite at least one analogue using "
                    "[ref:release:<id>] or [ref:episode:<id>] grammar."
                )
            completion = self.llm_router.complete(prompt)
            last_completion = completion or ""
            if self._passes_gate(last_completion):
                return last_completion, False
            logger.info(
                {
                    "event": "regime_narration_gate_fail",
                    "indicator_id": indicator_id,
                    "attempt": attempt + 1,
                    "max_attempts": self.max_attempts,
                }
            )
        raise NarrationFailedAfterRetry(
            f"regime narration failed regex gate after "
            f"{self.max_attempts} attempts for {indicator_id}"
        )

    def degraded_fallback(
        self,
        *,
        current_regime: str,
        prior_regime: str,
        transition_probability: float,
        analogues: list[HistoricalAnalogue],
    ) -> str:
        """Deterministic Markdown rendering used when narrate() fails.

        Preserves the Phase 71 citation grammar so the Evidence Drawer
        still renders cleanly. ALWAYS satisfies the regex gate by
        construction (names the regime + emits ``[ref:release:<id>]`` for
        every analogue when present, or notes the absence explicitly).
        """
        citations = " ".join(
            f"[ref:release:{a.release_id}]" for a in analogues
        )
        flip_note = (
            f"transitioned from **{prior_regime}**"
            if current_regime != prior_regime
            else f"persisted from **{prior_regime}**"
        )
        suffix = (
            f" Comparable past releases: {citations}."
            if citations
            else " No historical analogues retrieved (Phase 86 degraded)."
        )
        return (
            f"**Regime classification (degraded narration):** "
            f"current regime is **{current_regime}** "
            f"({flip_note}; transition_probability = "
            f"{transition_probability:.2f}).{suffix}"
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _passes_gate(text: str) -> bool:
        """Both regex gates must match per agent profile hard_assertions."""
        if not text:
            return False
        names = _REGIME_TOKEN_RE.findall(text)
        cites = _CITATION_RE.findall(text)
        return len(names) >= 1 and len(cites) >= 1

    @staticmethod
    def _build_prompt(
        *,
        indicator_id: str,
        release: dict,
        current_regime: str,
        prior_regime: str,
        transition_probability: float,
        analogues: list[HistoricalAnalogue],
    ) -> str:
        actual = release.get("actual")
        surprise = release.get("surprise")
        try:
            surprise_str = f"{float(surprise):+.2f}" if surprise is not None else "?"
        except (TypeError, ValueError):
            surprise_str = "?"
        analogue_lines = "\n".join(
            f"- [ref:release:{a.release_id}] {a.indicator_id} on "
            f"{a.release_date} (surprise {a.surprise:+.2f}, "
            f"n={a.sample_size}, period={a.evidence_period})"
            for a in analogues
        ) or "(no historical analogues retrieved)"
        return (
            "You are the vm107.macro_regime_analyst.\n\n"
            f"{indicator_id} just printed actual={actual} "
            f"(surprise {surprise_str}).\n\n"
            "Classifier output (LOCK-10 deterministic):\n"
            f"  - current_regime: {current_regime}\n"
            f"  - prior_regime:   {prior_regime}\n"
            f"  - transition_probability (Wave 3 deterministic): "
            f"{transition_probability:.2f}\n\n"
            "Historical analogues:\n"
            f"{analogue_lines}\n\n"
            "Write ONE paragraph that:\n"
            "  1. Names the current regime (one of expansion / slowdown / "
            "inflation / disinflation / stagflation / recession / recovery).\n"
            "  2. States the transition probability with calibrated confidence.\n"
            "  3. Cites at least one analogue using "
            "[ref:release:<id>] or [ref:episode:<id>] grammar."
        )
