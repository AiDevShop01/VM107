"""Deterministic prompt library — Phase 67 Plan 07 v1.

30+ templated reflection prompts across the 10 locked categories
(CONTEXT.md §4 + load-bearing constraint #5 — deterministic-first,
LLM enrichment additive only).

LOCKED ANTI-PATTERN — these phrasings are FORBIDDEN anywhere in this
file (regression-tested):
  * "How did you feel?"
  * "What went well?"

Every prompt MUST be specific (regime / discipline / pattern / execution
context anchored) AND target a concrete behavioral lever, not a generic
journaling cue.

Locked prompt taxonomy:
  DISCIPLINE / EXECUTION / REGIME / EMOTIONAL / LOCATION /
  PATIENCE / OVERTRADING / RISK / READINESS / EDGE_QUALITY

Locked intervention types:
  reflective / tactical / pattern-recognition / emotional / future-oriented

Locked intervention strengths:
  LOW / MODERATE / HIGH / CRITICAL
"""
from __future__ import annotations

from dataclasses import dataclass


PROMPT_LIBRARY_VERSION = "v1.0.0"


@dataclass(frozen=True)
class PromptTemplate:
    """One deterministic prompt template with substitution placeholders.

    `template` may contain placeholders like {regime}, {symbol},
    {confirmation_signal}, {pattern_name} which the synthesizer fills
    from the candidate's evidence_chain.
    """

    category: str
    intervention_type: str
    template: str
    default_emotional_load: float
    default_strength: str
    temporal_scale: str = "immediate-session"  # immediate-session | longitudinal


# ── DISCIPLINE ─────────────────────────────────────────────────────────────


_DISCIPLINE = [
    PromptTemplate(
        category="DISCIPLINE",
        intervention_type="pattern-recognition",
        template=(
            "You repeatedly entered before {confirmation_signal} during "
            "{regime} regime. What belief caused premature execution?"
        ),
        default_emotional_load=0.6,
        default_strength="HIGH",
    ),
    PromptTemplate(
        category="DISCIPLINE",
        intervention_type="reflective",
        template=(
            "Three discipline flags were raised in this session "
            "({flag_summary}). Which one repeats across the last 5 sessions?"
        ),
        default_emotional_load=0.5,
        default_strength="MODERATE",
    ),
    PromptTemplate(
        category="DISCIPLINE",
        intervention_type="tactical",
        template=(
            "Your rule violation in {symbol} ({pattern_name}) cost {pnl_r}R. "
            "What pre-trade check would have caught it?"
        ),
        default_emotional_load=0.55,
        default_strength="HIGH",
    ),
    PromptTemplate(
        category="DISCIPLINE",
        intervention_type="future-oriented",
        template=(
            "Tomorrow's session: which one rule, if broken once, would mean "
            "you stop trading for the day? Make it explicit now."
        ),
        default_emotional_load=0.4,
        default_strength="MODERATE",
        temporal_scale="longitudinal",
    ),
]


# ── EXECUTION ──────────────────────────────────────────────────────────────


_EXECUTION = [
    PromptTemplate(
        category="EXECUTION",
        intervention_type="reflective",
        template=(
            "Three trades opened within the last 5 minutes of the session. "
            "What pressure drove you to force these entries?"
        ),
        default_emotional_load=0.7,
        default_strength="HIGH",
    ),
    PromptTemplate(
        category="EXECUTION",
        intervention_type="tactical",
        template=(
            "Your average time-in-trade dropped {drop_pct}% from baseline. "
            "Were you exiting on price action or on emotional cues?"
        ),
        default_emotional_load=0.55,
        default_strength="MODERATE",
    ),
    PromptTemplate(
        category="EXECUTION",
        intervention_type="pattern-recognition",
        template=(
            "Entry timing slipped by {slippage_seconds}s on {trade_count} "
            "trades during {regime}. What was the recurring distraction?"
        ),
        default_emotional_load=0.5,
        default_strength="MODERATE",
    ),
]


# ── REGIME ─────────────────────────────────────────────────────────────────


_REGIME = [
    PromptTemplate(
        category="REGIME",
        intervention_type="pattern-recognition",
        template=(
            "Your edge zone shifted from {regime_from} to {regime_to} "
            "mid-session. Did you adapt or fight the change?"
        ),
        default_emotional_load=0.5,
        default_strength="HIGH",
    ),
    PromptTemplate(
        category="REGIME",
        intervention_type="reflective",
        template=(
            "You took {trade_count} trades in {regime} regime — your "
            "historical win rate there is {win_rate_pct}%. What signal "
            "told you THIS session was different?"
        ),
        default_emotional_load=0.45,
        default_strength="MODERATE",
    ),
    PromptTemplate(
        category="REGIME",
        intervention_type="tactical",
        template=(
            "Compression broke at {time} but you didn't size up the "
            "expansion. What stopped you?"
        ),
        default_emotional_load=0.4,
        default_strength="LOW",
    ),
]


# ── EMOTIONAL ──────────────────────────────────────────────────────────────


_EMOTIONAL = [
    PromptTemplate(
        category="EMOTIONAL",
        intervention_type="emotional",
        template=(
            "Sleep score {sleep_score} + {flag_count} discipline flags. "
            "What was the dominant feeling at the moment of each flag?"
        ),
        default_emotional_load=0.8,
        default_strength="HIGH",
    ),
    PromptTemplate(
        category="EMOTIONAL",
        intervention_type="reflective",
        template=(
            "After the {trade_id} loss, the next entry came in "
            "{recovery_seconds}s. Describe the bridge thought between "
            "those two clicks."
        ),
        default_emotional_load=0.85,
        default_strength="HIGH",
    ),
    PromptTemplate(
        category="EMOTIONAL",
        intervention_type="future-oriented",
        template=(
            "Identify one body sensation that consistently precedes a "
            "discipline break this week. What is the earliest moment you "
            "could intercept it?"
        ),
        default_emotional_load=0.7,
        default_strength="MODERATE",
        temporal_scale="longitudinal",
    ),
]


# ── LOCATION ───────────────────────────────────────────────────────────────


_LOCATION = [
    PromptTemplate(
        category="LOCATION",
        intervention_type="pattern-recognition",
        template=(
            "Entries at {price_zone} have a {win_rate_pct}% historical "
            "rate. Today's {trade_id} ignored that zone. Why this one?"
        ),
        default_emotional_load=0.4,
        default_strength="MODERATE",
    ),
    PromptTemplate(
        category="LOCATION",
        intervention_type="tactical",
        template=(
            "Your stop placement on {symbol} averaged {stop_distance_atr}× "
            "ATR — outside the {regime} norm. What chart feature justified it?"
        ),
        default_emotional_load=0.45,
        default_strength="MODERATE",
    ),
    PromptTemplate(
        category="LOCATION",
        intervention_type="reflective",
        template=(
            "Three trades entered at extension highs instead of the "
            "pullback. Which one was opportunity, which were FOMO?"
        ),
        default_emotional_load=0.55,
        default_strength="MODERATE",
    ),
]


# ── PATIENCE ───────────────────────────────────────────────────────────────


_PATIENCE = [
    PromptTemplate(
        category="PATIENCE",
        intervention_type="reflective",
        template=(
            "Average wait between setups dropped to {wait_minutes} min "
            "(baseline {baseline_minutes}). Which trade today was the "
            "first impatient one?"
        ),
        default_emotional_load=0.5,
        default_strength="MODERATE",
    ),
    PromptTemplate(
        category="PATIENCE",
        intervention_type="future-oriented",
        template=(
            "Define ONE minimum confirmation you will not skip tomorrow, "
            "even when bored."
        ),
        default_emotional_load=0.4,
        default_strength="MODERATE",
        temporal_scale="longitudinal",
    ),
    PromptTemplate(
        category="PATIENCE",
        intervention_type="tactical",
        template=(
            "You sat in {symbol} for {hold_minutes}min waiting for "
            "{confirmation_signal}, then bailed. What changed in the tape?"
        ),
        default_emotional_load=0.5,
        default_strength="LOW",
    ),
]


# ── OVERTRADING ────────────────────────────────────────────────────────────


_OVERTRADING = [
    PromptTemplate(
        category="OVERTRADING",
        intervention_type="pattern-recognition",
        template=(
            "{trade_count} trades in a session where your edge takes "
            "{historical_count}. Identify the inflection trade where "
            "execution shifted from selective to compulsive."
        ),
        default_emotional_load=0.65,
        default_strength="HIGH",
    ),
    PromptTemplate(
        category="OVERTRADING",
        intervention_type="emotional",
        template=(
            "After the early {early_pnl}R drawdown, position count "
            "doubled. What did each additional entry feel like it would fix?"
        ),
        default_emotional_load=0.8,
        default_strength="CRITICAL",
    ),
    PromptTemplate(
        category="OVERTRADING",
        intervention_type="future-oriented",
        template=(
            "Set a hard trade-count ceiling for the next session based on "
            "your historical edge density."
        ),
        default_emotional_load=0.45,
        default_strength="MODERATE",
        temporal_scale="longitudinal",
    ),
]


# ── RISK ───────────────────────────────────────────────────────────────────


_RISK = [
    PromptTemplate(
        category="RISK",
        intervention_type="tactical",
        template=(
            "Average position size grew {size_growth_pct}% mid-session "
            "while win rate held flat. Was that conviction or compensation?"
        ),
        default_emotional_load=0.6,
        default_strength="HIGH",
    ),
    PromptTemplate(
        category="RISK",
        intervention_type="pattern-recognition",
        template=(
            "Your stop got moved on {moves_count} trades — {moves_against} "
            "against you. What was the rule you bent?"
        ),
        default_emotional_load=0.65,
        default_strength="HIGH",
    ),
    PromptTemplate(
        category="RISK",
        intervention_type="future-oriented",
        template=(
            "Define the maximum daily loss at which you would walk away "
            "without rationalizing one more trade."
        ),
        default_emotional_load=0.5,
        default_strength="MODERATE",
        temporal_scale="longitudinal",
    ),
]


# ── READINESS ──────────────────────────────────────────────────────────────


_READINESS = [
    PromptTemplate(
        category="READINESS",
        intervention_type="reflective",
        template=(
            "Pre-session readiness scored {readiness_score}. Looking back, "
            "what single check would have shifted you to YELLOW or RED?"
        ),
        default_emotional_load=0.45,
        default_strength="MODERATE",
        temporal_scale="longitudinal",
    ),
    PromptTemplate(
        category="READINESS",
        intervention_type="future-oriented",
        template=(
            "Tomorrow morning: which one readiness metric, if RED, would "
            "make you cut size by 50% before market open?"
        ),
        default_emotional_load=0.4,
        default_strength="MODERATE",
        temporal_scale="longitudinal",
    ),
    PromptTemplate(
        category="READINESS",
        intervention_type="emotional",
        template=(
            "Your readiness drifted from {readiness_start} to "
            "{readiness_end} across the session. Where did it break?"
        ),
        default_emotional_load=0.55,
        default_strength="MODERATE",
        temporal_scale="longitudinal",
    ),
]


# ── EDGE_QUALITY ───────────────────────────────────────────────────────────


_EDGE_QUALITY = [
    PromptTemplate(
        category="EDGE_QUALITY",
        intervention_type="pattern-recognition",
        template=(
            "{a_plus_count} A+ setups passed by; you entered "
            "{b_grade_count} B-grade trades. What kept you out of the "
            "A+ list?"
        ),
        default_emotional_load=0.5,
        default_strength="HIGH",
    ),
    PromptTemplate(
        category="EDGE_QUALITY",
        intervention_type="reflective",
        template=(
            "Best trade today: {best_trade_id}. Worst: {worst_trade_id}. "
            "What did the best one have that you ignored in the worst?"
        ),
        default_emotional_load=0.4,
        default_strength="MODERATE",
    ),
    PromptTemplate(
        category="EDGE_QUALITY",
        intervention_type="tactical",
        template=(
            "Your edge filter ({filter_name}) failed on {failure_count} "
            "trades in {regime}. Refine the filter or stop trading "
            "{regime}?"
        ),
        default_emotional_load=0.5,
        default_strength="MODERATE",
        temporal_scale="longitudinal",
    ),
]


PROMPT_TEMPLATES: dict[str, list[PromptTemplate]] = {
    "DISCIPLINE": _DISCIPLINE,
    "EXECUTION": _EXECUTION,
    "REGIME": _REGIME,
    "EMOTIONAL": _EMOTIONAL,
    "LOCATION": _LOCATION,
    "PATIENCE": _PATIENCE,
    "OVERTRADING": _OVERTRADING,
    "RISK": _RISK,
    "READINESS": _READINESS,
    "EDGE_QUALITY": _EDGE_QUALITY,
}
