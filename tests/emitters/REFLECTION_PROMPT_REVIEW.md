# Reflection Prompt — Manual UAT Review

Per Phase 67 VALIDATION.md row 5 — subjective evaluation of 4-prompt
narrative coherence + specificity. Automated tests cover shape /
eligibility / diversity / coherence math; **set-level felt quality**
requires a human reviewer.

## Review Method

1. Generate 10 sample sets across varied session profiles:
   ```bash
   cd VM107
   python -m emitters.reflection_prompt_emitter --account-id 42 --date 2026-05-25 --count 10
   ```
   (or hand-run via Python REPL when the CLI is not yet wired)

2. For each set, evaluate every prompt against the rubric below.
   Record findings in the "Sample Sets Reviewed" section.

## Rubric — apply per SET (4 prompts)

- [ ] **Emotional safety** — set as a whole feels grounded, not
  anxiety-inducing. Sum of perceived emotional load ≤ "uncomfortable
  but bearable".
- [ ] **Temporal mix** — at least 1 immediate-session prompt + at
  least 1 longitudinal prompt present. The set should NOT be 4
  immediate or 4 longitudinal.
- [ ] **No contradictions** — no prompt accuses the trader of being
  "too aggressive" while another accuses "too passive" (and the four
  other locked CONTRADICTION_PAIRS).
- [ ] **Specificity** — every prompt names a regime, discipline flag,
  pattern, or execution detail; **zero** generic "how did you feel?"
  / "what went well?" phrasings.
- [ ] **Behavioral target distinct from outcome reporting** — prompts
  ask "what belief / what pressure / what signal" — they do NOT just
  restate the P&L outcome.
- [ ] **Diversity** — no more than 2 prompts share the same category
  (or 3 under a dominant_session_theme); ≤1 share intervention_type
  (or ≤2 under dominant theme); ≤1 share originating_pattern.

## Rubric — apply per PROMPT

- [ ] `category` matches the prompt's actual focus
- [ ] `intervention_strength` matches the prompt's bluntness (CRITICAL
      reserved for true escalations only)
- [ ] `intervention_type` matches the cognitive operation requested
- [ ] `base_prompt` reads as a complete, single-sentence question
- [ ] `llm_enriched_prompt` (when present) preserves the behavioral
      target — does NOT swap category or strength
- [ ] `evidence_chain` references real session evidence (every {kind,
      ref, weight} item is traceable)
- [ ] `prompt_version` is stamped from the deterministic library

## Sample Sets Reviewed

Fill in during UAT cycle.

### Set 1 — `<set_id>`
- **Profile:** <e.g., 5 trades, RANGE regime, 3 discipline flags, worsening trajectory>
- **Result:** <PASS / PARTIAL / FAIL>
- **Notes:** <what worked / what didn't>

### Set 2 — `<set_id>`
- **Profile:** <...>
- **Result:** <...>
- **Notes:** <...>

<!-- repeat for 10 sets total -->

## Summary

- **Total sets reviewed:** _ / 10
- **PASS:** _
- **PARTIAL:** _
- **FAIL:** _

## Findings

- <list any recurring quality issues>
- <list any prompt templates that should be retired or revised>
- <list any taxonomy gaps — e.g. missing intervention types>

## Action Items

- [ ] Tune scoring weights / diversity caps based on findings
- [ ] Add / retire prompt templates per category
- [ ] File issues in Plan 13 / Phase 70 backlog
