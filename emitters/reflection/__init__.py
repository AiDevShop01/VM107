"""VM107 ReflectionPrompt subpackage — Phase 67 Plan 07 (REQ-67-4).

Five-stage progressive enrichment pipeline:

    1. TradeObservation   — concrete observable trade evidence (VM100 trade outcomes)
    2. BehavioralInterpretation — discipline flags + mentor narrative (Phase 60)
    3. PatternContext     — cross-trade patterns within session (Phase 54)
    4. LongitudinalContext — behavioral evolution + adaptive recommendation (Phase 62)
    5. ReflectionPromptSynthesizer — deterministic candidate scoring + diversity + coherence

Deterministic-first + NoveltyEngine gate + optional LLM enrichment (Phase 66 lock).
LLM enrichment is additive only — NEVER replaces the deterministic prompt.

Locked prompt taxonomy (10 categories):
    DISCIPLINE / EXECUTION / REGIME / EMOTIONAL / LOCATION /
    PATIENCE / OVERTRADING / RISK / READINESS / EDGE_QUALITY

Intervention types (5):
    reflective / tactical / pattern-recognition / emotional / future-oriented

Intervention strengths (4):
    LOW / MODERATE / HIGH / CRITICAL
"""
