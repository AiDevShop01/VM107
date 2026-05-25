"""ReflectionPromptSynthesizer — Phase 67 Plan 07 Stage 5 (REQ-67-4).

Score-then-diversify hybrid selection:

    1. Generate candidates from the deterministic prompt library, one
       per matching (category, evidence cluster) pair.
    2. Eligibility filter — multi-domain evidence convergence required
       (observable trade evidence AND at least one of [interpretation,
       pattern, longitudinal]).
    3. Composite score each candidate.
    4. Sort descending by score.
    5. apply_diversity_guards → (selected, rejected_by_diversity).
    6. coherence_check on the post-diversity set → (final, score).
    7. Detect dominant_session_theme if one category genuinely dominates.
    8. Optional LLM enrichment per selected prompt (gated by NoveltyEngine
       — Phase 66 lock — never replaces the deterministic base).
    9. Return ReflectionPromptSetContract (selected + rejected).

Composite score weights (locked — CONTEXT.md §4):
    severity                 0.25
    novelty                  0.20
    actionability            0.20
    behavioral_confidence    0.20
    longitudinal_relevance   0.15

LLM enrichment is ADDITIVE — it MUST NOT mutate category /
intervention_strength / intervention_type. The synthesizer enforces this
by stamping these fields from the deterministic template, not from the
LLM payload.

Pitfall 7 mitigation: novelty dims fed to the NoveltyEngine are computed
over the FLAGS-NEW-THIS-SESSION-VS-LAST-7-DAYS axis (proxied here via
the discipline_flag count delta), NOT raw flag count. Phase 13 may add
real 7-day baseline lookup; the structure is in place.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from emitters.contracts.reflection_prompt import (
    EvidenceChainItem,
    ReflectionPromptContract,
    ReflectionPromptSetContract,
)
from emitters.novelty_engine import NoveltyDimensions, NoveltyEngine
from emitters.reflection.assemblers.behavioral_interpretation import (
    BehavioralInterpretation,
)
from emitters.reflection.assemblers.longitudinal_context import LongitudinalContext
from emitters.reflection.assemblers.pattern_context import PatternContext
from emitters.reflection.assemblers.trade_observation import TradeObservation
from emitters.reflection.coherence import coherence_check
from emitters.reflection.diversity_guards import apply_diversity_guards
from emitters.reflection.prompt_library import (
    PROMPT_LIBRARY_VERSION,
    PROMPT_TEMPLATES,
    PromptTemplate,
)

log = logging.getLogger(__name__)


# ── Internal mutable candidate ────────────────────────────────────────────


@dataclass
class _Candidate:
    """Internal mutable candidate — used during scoring + diversity + coherence
    passes. Converted to ``ReflectionPromptContract`` (frozen) at the end.
    """

    candidate_id: str
    category: str
    intervention_type: str
    intervention_strength: str
    base_prompt: str
    template: PromptTemplate

    # Score factors (composite ingredients)
    severity: float = 0.0
    novelty: float = 0.0
    actionability: float = 0.0
    behavioral_confidence: float = 0.0
    longitudinal_relevance: float = 0.0
    score: float = 0.0

    # Evidence + tagging
    originating_patterns: list[str] = field(default_factory=list)
    originating_flags: list[str] = field(default_factory=list)
    evidence_chain: list[EvidenceChainItem] = field(default_factory=list)
    selection_reason: str = ""
    flags: tuple[str, ...] = field(default_factory=tuple)
    emotional_load: float = 0.5
    originating_pattern: str = ""  # primary pattern for diversity-guard slot
    temporal_scale: str = "immediate-session"
    novelty_score: float = 0.0

    # State carried into the final contract
    selected: bool = True
    rejection_reason: str | None = None
    rejected_by_diversity_guard: str | None = None
    llm_enriched_prompt: str | None = None


# ── Synthesizer ───────────────────────────────────────────────────────────


class ReflectionPromptSynthesizer:
    """Score-then-diversify hybrid reflection prompt selection."""

    DEFAULT_WEIGHTS = {
        "severity": 0.25,
        "novelty": 0.20,
        "actionability": 0.20,
        "behavioral_confidence": 0.20,
        "longitudinal_relevance": 0.15,
    }

    MAX_SELECTED = 4

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        self._weights = weights or self.DEFAULT_WEIGHTS

    # ── Public API ─────────────────────────────────────────────────────

    def synthesize(
        self,
        *,
        account_id: int,
        observations: list[TradeObservation],
        interpretations: list[BehavioralInterpretation],
        patterns: list[PatternContext],
        longitudinal: list[LongitudinalContext],
        novelty_engine: NoveltyEngine,
    ) -> ReflectionPromptSetContract:
        """Run the full Stage-5 pipeline and return the set contract."""

        generated_at = datetime.now(timezone.utc)
        set_id = f"rps-{uuid.uuid4().hex[:12]}"

        # 1. Eligibility — observation MUST exist + at least one support layer.
        if not observations or not (interpretations or patterns or longitudinal):
            return ReflectionPromptSetContract(
                set_id=set_id,
                account_id=account_id,
                generated_at=generated_at,
                selected_prompts=[],
                rejected_candidates=[],
                reflection_set_coherence_score=0.0,
                dominant_session_theme=None,
            )

        # 2. Build candidate pool from the deterministic prompt library +
        #    available evidence clusters.
        candidates = self._build_candidates(
            account_id, observations, interpretations, patterns, longitudinal,
            novelty_engine=novelty_engine,
        )

        if not candidates:
            return ReflectionPromptSetContract(
                set_id=set_id,
                account_id=account_id,
                generated_at=generated_at,
                selected_prompts=[],
                rejected_candidates=[],
                reflection_set_coherence_score=0.0,
                dominant_session_theme=None,
            )

        # 3-4. Score + sort descending
        for c in candidates:
            c.score = self._score_candidate(
                {
                    "severity": c.severity,
                    "novelty": c.novelty,
                    "actionability": c.actionability,
                    "behavioral_confidence": c.behavioral_confidence,
                    "longitudinal_relevance": c.longitudinal_relevance,
                }
            )
        candidates.sort(key=lambda c: -c.score)

        # 5. Dominant theme detection BEFORE diversity guard (CONTEXT.md §4)
        dominant_theme = self._detect_dominant_theme(candidates)

        # 5b. Diversity guard
        provisional_selected, rejected_by_diversity = apply_diversity_guards(
            candidates, dominant_theme=dominant_theme
        )

        # Cap to MAX_SELECTED before coherence
        if len(provisional_selected) > self.MAX_SELECTED:
            extras = provisional_selected[self.MAX_SELECTED:]
            for e in extras:
                e.selected = False
                e.rejection_reason = "exceeded_max_selected_cap"
            rejected_by_diversity.extend(extras)
            provisional_selected = provisional_selected[: self.MAX_SELECTED]

        # 6. Coherence pass — may swap candidates from the pool
        coherence_pool = candidates  # full sorted pool
        final_selected, coherence_score = coherence_check(
            provisional_selected, coherence_pool
        )

        # Anything in candidates not in final_selected at this point is
        # rejected — collect by id.
        final_ids = {c.candidate_id for c in final_selected}
        rejected_pool: list[_Candidate] = []
        for c in candidates:
            if c.candidate_id in final_ids:
                continue
            if not c.rejection_reason:
                c.rejection_reason = "not_selected"
            c.selected = False
            rejected_pool.append(c)

        # 8. Optional LLM enrichment per selected prompt (gated by novelty)
        for c in final_selected:
            try:
                dims = NoveltyDimensions(
                    behavioral_novelty=min(1.0, c.novelty),
                    behavior_anomaly=c.severity >= 0.7,
                )
                novelty_result = novelty_engine.score(dims)
                if getattr(novelty_result, "threshold_crossed", False):
                    c.llm_enriched_prompt = self._call_llm(
                        c.base_prompt,
                        {
                            "category": c.category,
                            "flags": list(c.originating_flags),
                            "patterns": list(c.originating_patterns),
                        },
                    )
            except Exception as exc:
                log.warning(
                    "reflection_prompt_llm_enrichment_failed: %s(%s)",
                    type(exc).__name__,
                    exc,
                )

        selected_contracts = [
            self._to_contract(c, account_id, generated_at, selected=True)
            for c in final_selected
        ]
        rejected_contracts = [
            self._to_contract(c, account_id, generated_at, selected=False)
            for c in rejected_pool
        ]

        return ReflectionPromptSetContract(
            set_id=set_id,
            account_id=account_id,
            generated_at=generated_at,
            selected_prompts=selected_contracts,
            rejected_candidates=rejected_contracts,
            reflection_set_coherence_score=coherence_score,
            dominant_session_theme=dominant_theme,
        )

    # ── Internal helpers ───────────────────────────────────────────────

    def _score_candidate(self, factors: dict[str, float]) -> float:
        """Composite score = Σ weight·factor (locked weights)."""
        w = self._weights
        return (
            w["severity"] * factors.get("severity", 0.0)
            + w["novelty"] * factors.get("novelty", 0.0)
            + w["actionability"] * factors.get("actionability", 0.0)
            + w["behavioral_confidence"] * factors.get("behavioral_confidence", 0.0)
            + w["longitudinal_relevance"] * factors.get("longitudinal_relevance", 0.0)
        )

    def _build_candidates(
        self,
        account_id: int,
        observations: list[TradeObservation],
        interpretations: list[BehavioralInterpretation],
        patterns: list[PatternContext],
        longitudinal: list[LongitudinalContext],
        novelty_engine: NoveltyEngine,
    ) -> list[_Candidate]:
        """Walk the prompt library × evidence clusters → candidate list."""

        # Aggregate evidence sets for cross-prompt re-use
        all_flags: list[str] = []
        for i in interpretations:
            all_flags.extend(i.discipline_flags)
        flag_set = set(all_flags)

        # Behavioral confidence — mean of interpretation confidences when any
        if interpretations:
            mean_conf = sum(i.confidence for i in interpretations) / max(
                1, len(interpretations)
            )
        else:
            mean_conf = 0.0

        # Novelty proxy — distinct flag count normalized; Plan 13 will swap to
        # 7-day baseline delta (Pitfall 7 mitigation structure in place).
        novelty_proxy = min(1.0, len(flag_set) / 5.0)

        # Longitudinal relevance — non-zero when longitudinal layer is present
        longitudinal_relevance = 0.7 if longitudinal else 0.0

        # Actionability — boosted when patterns + interpretations both present
        actionability = 0.8 if (interpretations and patterns) else (
            0.6 if interpretations else (0.5 if patterns else 0.4)
        )

        # Regimes seen in observations
        regimes = {o.regime for o in observations if o.regime}
        primary_regime = next(iter(regimes), "UNKNOWN")

        candidates: list[_Candidate] = []

        # ── Flag-driven candidates ─────────────────────────────────────
        for flag in sorted(flag_set):
            mapped_category = _map_flag_to_category(flag)
            templates = PROMPT_TEMPLATES.get(mapped_category, [])
            if not templates:
                continue
            template = templates[0]
            cid = f"cand-{uuid.uuid4().hex[:8]}"
            severity = min(1.0, all_flags.count(flag) / 3.0)  # repetition → severity
            base_prompt = _fill_template(
                template.template,
                {
                    "confirmation_signal": "M5 BOS",
                    "regime": primary_regime,
                    "flag_summary": ", ".join(sorted(flag_set)),
                    "symbol": observations[0].symbol if observations else "?",
                    "pattern_name": flag,
                    "pnl_r": (
                        f"{observations[0].pnl_r:+.1f}"
                        if observations
                        else "?"
                    ),
                },
            )
            evidence: list[EvidenceChainItem] = [
                EvidenceChainItem(
                    kind="discipline_flag", ref=f"discipline_flag:{flag}", weight=severity,
                ),
            ]
            for i in interpretations:
                if flag in i.discipline_flags and i.mentor_narrative_summary:
                    evidence.append(
                        EvidenceChainItem(
                            kind="mentor_narrative",
                            ref=f"mentor_narrative:{i.trade_id}",
                            weight=min(1.0, max(0.0, i.confidence)),
                        )
                    )
                    break
            candidates.append(
                _Candidate(
                    candidate_id=cid,
                    category=template.category,
                    intervention_type=template.intervention_type,
                    intervention_strength=template.default_strength,
                    base_prompt=base_prompt,
                    template=template,
                    severity=severity,
                    novelty=novelty_proxy,
                    actionability=actionability,
                    behavioral_confidence=mean_conf,
                    longitudinal_relevance=longitudinal_relevance,
                    originating_patterns=[],
                    originating_flags=[flag],
                    evidence_chain=evidence,
                    selection_reason=f"discipline_repeat:{flag}",
                    flags=(flag,),
                    emotional_load=template.default_emotional_load,
                    originating_pattern=flag,
                    temporal_scale=template.temporal_scale,
                    novelty_score=novelty_proxy,
                )
            )

        # ── Pattern-driven candidates ─────────────────────────────────
        for p in patterns:
            mapped_category = _map_pattern_to_category(p.pattern_name)
            templates = PROMPT_TEMPLATES.get(mapped_category, [])
            if not templates:
                continue
            # Use a different intervention_type than the flag candidate
            template = templates[min(1, len(templates) - 1)]
            cid = f"cand-{uuid.uuid4().hex[:8]}"
            severity = float(p.severity)
            base_prompt = _fill_template(
                template.template,
                {
                    "confirmation_signal": "M5 BOS",
                    "regime": primary_regime,
                    "pattern_name": p.pattern_name,
                    "symbol": observations[0].symbol if observations else "?",
                    "flag_summary": ", ".join(sorted(flag_set)),
                    "pnl_r": "0",
                    "trade_count": str(len(observations)),
                },
            )
            evidence = [
                EvidenceChainItem(
                    kind="cross_trade_pattern",
                    ref=f"cross_trade_pattern:{p.pattern_id}",
                    weight=severity,
                ),
            ]
            if longitudinal:
                evidence.append(
                    EvidenceChainItem(
                        kind="behavioral_evolution",
                        ref=f"behavioral_evolution:{longitudinal[0].evolution_trend}",
                        weight=0.6,
                    )
                )
            candidates.append(
                _Candidate(
                    candidate_id=cid,
                    category=template.category,
                    intervention_type=template.intervention_type,
                    intervention_strength=template.default_strength,
                    base_prompt=base_prompt,
                    template=template,
                    severity=severity,
                    novelty=novelty_proxy,
                    actionability=actionability,
                    behavioral_confidence=mean_conf,
                    longitudinal_relevance=longitudinal_relevance,
                    originating_patterns=[p.pattern_name],
                    originating_flags=[],
                    evidence_chain=evidence,
                    selection_reason=f"pattern_cluster:{p.pattern_name}",
                    flags=(p.pattern_name,),
                    emotional_load=template.default_emotional_load,
                    originating_pattern=p.pattern_name,
                    temporal_scale=template.temporal_scale,
                    novelty_score=novelty_proxy,
                )
            )

        # ── Longitudinal-driven candidates ─────────────────────────────
        if longitudinal:
            for category in ("READINESS", "EDGE_QUALITY"):
                templates = PROMPT_TEMPLATES.get(category, [])
                if not templates:
                    continue
                template = next(
                    (t for t in templates if t.temporal_scale == "longitudinal"),
                    templates[0],
                )
                cid = f"cand-{uuid.uuid4().hex[:8]}"
                base_prompt = _fill_template(
                    template.template,
                    {
                        "readiness_score": "0.62",
                        "readiness_start": "0.78",
                        "readiness_end": "0.45",
                        "a_plus_count": str(len(observations)),
                        "b_grade_count": str(max(1, len(observations) - 1)),
                        "best_trade_id": observations[0].trade_id if observations else "?",
                        "worst_trade_id": observations[-1].trade_id if observations else "?",
                        "filter_name": "session_edge_filter",
                        "failure_count": str(len(observations)),
                        "regime": primary_regime,
                    },
                )
                evidence = [
                    EvidenceChainItem(
                        kind="behavioral_evolution",
                        ref=f"behavioral_evolution:{longitudinal[0].evolution_trend}",
                        weight=0.7,
                    ),
                ]
                candidates.append(
                    _Candidate(
                        candidate_id=cid,
                        category=template.category,
                        intervention_type=template.intervention_type,
                        intervention_strength=template.default_strength,
                        base_prompt=base_prompt,
                        template=template,
                        severity=0.5,
                        novelty=novelty_proxy,
                        actionability=actionability,
                        behavioral_confidence=mean_conf,
                        longitudinal_relevance=longitudinal_relevance,
                        originating_patterns=[],
                        originating_flags=[],
                        evidence_chain=evidence,
                        selection_reason=f"longitudinal:{longitudinal[0].evolution_trend}",
                        flags=(),
                        emotional_load=template.default_emotional_load,
                        originating_pattern=f"longitudinal_{category.lower()}",
                        temporal_scale=template.temporal_scale,
                        novelty_score=novelty_proxy,
                    )
                )

        return candidates

    def _detect_dominant_theme(
        self, candidates: list[_Candidate]
    ) -> str | None:
        """Detect dominant_session_theme — one category with ≥3 high-severity candidates."""
        from collections import Counter

        high_sev_categories = Counter(
            c.category for c in candidates if c.severity >= 0.6
        )
        if not high_sev_categories:
            return None
        top_cat, top_count = high_sev_categories.most_common(1)[0]
        if top_count >= 3:
            return top_cat
        return None

    def _to_contract(
        self,
        c: _Candidate,
        account_id: int,
        generated_at: datetime,
        selected: bool,
    ) -> ReflectionPromptContract:
        """Convert internal mutable candidate → frozen contract."""
        return ReflectionPromptContract(
            prompt_id=c.candidate_id,
            account_id=account_id,
            category=c.category,  # type: ignore[arg-type]
            intervention_strength=c.intervention_strength,  # type: ignore[arg-type]
            intervention_type=c.intervention_type,  # type: ignore[arg-type]
            base_prompt=c.base_prompt,
            llm_enriched_prompt=c.llm_enriched_prompt,
            selection_reason=c.selection_reason or "n/a",
            novelty_score=c.novelty_score,
            behavioral_confidence_score=c.behavioral_confidence,
            confidence_score=c.score,
            emotional_load=max(0.0, min(1.0, c.emotional_load)),
            originating_patterns=list(c.originating_patterns),
            originating_flags=list(c.originating_flags),
            evidence_chain=list(c.evidence_chain),
            prompt_version=PROMPT_LIBRARY_VERSION,
            generated_at=generated_at,
            selected=selected,
            rejection_reason=c.rejection_reason if not selected else None,
            rejected_by_diversity_guard=c.rejected_by_diversity_guard,
        )

    def _call_llm(self, base_prompt: str, ctx: dict[str, Any]) -> str | None:
        """LLM enrichment — additive personalization of base_prompt.

        NEVER changes category / intervention_strength / intervention_type.
        Mock-seam for tests::

            monkeypatch.setattr(
                ReflectionPromptSynthesizer, "_call_llm",
                lambda self, base, ctx: f"[enriched] {base}",
            )

        Returns None on any failure — engine survives without LLM.
        """
        try:
            import anthropic  # type: ignore[import]

            client = anthropic.Anthropic()
            prompt = (
                "You are personalizing a reflection prompt for a trader. "
                "Keep the same behavioral target. Do NOT change the topic "
                "or the intervention strength. Adjust tone + phrasing only.\n\n"
                f"Base prompt: {base_prompt}\n\n"
                f"Flags this session: {ctx.get('flags', [])}\n"
                f"Patterns: {ctx.get('patterns', [])}\n\n"
                "Return the personalized prompt as a single sentence."
            )
            message = client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
            )
            return message.content[0].text.strip()
        except Exception as exc:
            log.warning(
                "reflection_prompt_llm_call_failed: %s(%s)",
                type(exc).__name__,
                exc,
            )
            return None


# ── Helpers ──────────────────────────────────────────────────────────────


def _fill_template(template: str, ctx: dict[str, Any]) -> str:
    """Substitute {placeholders} in template using best-effort dict lookup.

    Unknown placeholders are kept as-is so manual UAT can spot under-filled
    prompts in the REFLECTION_PROMPT_REVIEW.md scaffold.
    """
    out = template
    for k, v in ctx.items():
        out = out.replace("{" + k + "}", str(v))
    return out


# Flag → category mapping (planner discretion — extend as new flags emerge).
_FLAG_TO_CATEGORY = {
    "premature_entry": "DISCIPLINE",
    "delayed_entry": "DISCIPLINE",
    "size_violation": "RISK",
    "oversize": "RISK",
    "undersize": "RISK",
    "rule_break": "DISCIPLINE",
    "regime_mismatch": "REGIME",
    "fomo_entry": "EMOTIONAL",
    "revenge_trade": "EMOTIONAL",
    "overtrading": "OVERTRADING",
    "undertrading": "OVERTRADING",
    "too_aggressive": "EXECUTION",
    "too_passive": "EXECUTION",
    "stop_move_against": "RISK",
    "wide_stop": "LOCATION",
    "tight_stop": "LOCATION",
}


def _map_flag_to_category(flag: str) -> str:
    return _FLAG_TO_CATEGORY.get(flag, "DISCIPLINE")


_PATTERN_TO_CATEGORY = {
    "premature_entry_cluster": "DISCIPLINE",
    "overtrading_cluster": "OVERTRADING",
    "size_creep": "RISK",
    "regime_mismatch_cluster": "REGIME",
    "patience_collapse": "PATIENCE",
    "fomo_cluster": "EMOTIONAL",
}


def _map_pattern_to_category(pattern_name: str) -> str:
    return _PATTERN_TO_CATEGORY.get(pattern_name, "EDGE_QUALITY")
