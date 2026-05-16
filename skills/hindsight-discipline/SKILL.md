---
name: hindsight-discipline
description: >
  Constitutional skill enforcing epistemic discipline when referencing or interpreting
  counterfactual scenario outcomes. Prevents agents from treating hypothetical
  alternative exits as omniscient ground truth or from phrasing analysis as
  "you should have done X" certainty claims.
version: "1.0.0"
phase: 61
scope: constitutional
trigger_patterns:
  - "counterfactual"
  - "alternative exit"
  - "what if"
  - "could have"
  - "would have"
  - "hypothetical"
  - "if you had"
  - "hindsight"
  - "[ref:counterfactual"
allowed_tools:
  - get_counterfactual
  - get_counterfactuals_for_execution
  - lookup_counterfactual_scenario
tags: [phase-61, constitutional, counterfactual, hindsight-guard, epistemic-discipline]
---

# Hindsight Discipline

## Why This Skill Exists

Phase 61 introduces counterfactual scenario outcomes — deterministic simulations of
"what if the stop had been placed at a different level?" These outcomes are valuable
analytical tools. They are NOT omniscient truth. They are not evidence that a trader
made a mistake. They are not optimization targets.

The most dangerous epistemic failure in counterfactual analysis is treating a
simulation outcome with 20/20 hindsight — as if the trader could have known, at
trade entry, that a different stop level would have produced a better outcome.

**Phase 61 is the most epistemically dangerous phase in the entire roadmap.**
This skill is the primary guard against hindsight contamination in agent output.

## The Three Prohibited Framings

**Framing 1: Certainty about alternative outcomes**

BANNED: "You should have placed the stop at 1.0750 — it would have yielded 1.3R."
BANNED: "The alternative stop of ATR 1.0x would have given you a better result."
BANNED: "Clearly the ATR stop was the right choice here."

ALLOWED: "Under the ATR 1.0x alternative stop scenario (truth_mode=COUNTERFACTUAL),
         the simulation produced a hypothetical_r of 1.3 — 0.8R above the as-traded
         result. This outcome is conditioned on the simplified OHLC_BAR fidelity model
         and does not account for slippage, spread, or psychological execution factors."

**Framing 2: Comparing against omniscient exits**

BANNED: "The maximum favorable excursion was 1.5R — you left significant profit on the table."
BANNED: "A perfect trailing stop would have captured 2R."

ALLOWED: "The as-traded MFE was 1.5R [ref:counterfactual:...:hypothetical_mfe_r]. Whether
         any real trailing stop would have captured this depends on execution dynamics not
         modeled in this simulation."

**Framing 3: Optimization theater**

BANNED: "The best stop level would have been X."
BANNED: "Running this scenario across your trade history suggests you should optimize your stops to..."
BANNED: Ranking alternative scenarios by outcome to suggest parameter tuning.

ALLOWED: Describing what a specific, pre-registered scenario produced under a specific set
         of parameters, with explicit truth_mode=COUNTERFACTUAL framing.

## Required Framing When Citing Counterfactual Outcomes

Every citation referencing counterfactual outcome fields MUST include epistemic framing.
The minimum required framing is:

1. **truth_mode tag**: Always phrase as "under the [scenario_id] scenario (truth_mode=COUNTERFACTUAL)"
   or equivalent, NEVER as "the actual outcome was" or "in reality".

2. **Simulation fidelity caveat**: At least once per counterfactual reference block, include:
   "This simulation uses OHLC_BAR fidelity (M15 bars) and does not model slippage, spread,
   or intra-bar path dependency."

3. **No optimization claim**: If multiple scenarios are referenced, do NOT rank them as
   "better" or "worse" — describe each independently. Do not suggest which is "optimal."

4. **Information-at-T discipline**: Only reference information available at the evaluation
   point T (trade entry). Do not phrase analysis as if the alternative stop was chosen
   with knowledge of subsequent bar data.

## Citation Grammar for Counterfactual Fields

Counterfactual citations use the field segment to reference specific scenario outcomes:

```
[ref:counterfactual:counterfactual.stop.atr_1_0:hypothetical_r]
[ref:counterfactual:counterfactual.stop.atr_1_5:hypothetical_r]
[ref:counterfactual:counterfactual.stop.atr_1_0:r_delta]
```

The `field` segment follows the pattern `<scenario_id>:<outcome_field>` where
dots are permitted in the scenario_id portion (Option B grammar extension, Phase 61-01).

Artifact-level citations (referencing a specific counterfactual_id UUID) use:
```
[ref:counterfactual:cf_<uuid>]
```

## What Counterfactual Output Is

Counterfactual output is:
- A deterministic simulation of a pre-registered, pre-committed scenario
- Conditioned on the OHLC bar data available at the canonical replay horizon
- Bounded by truth_mode=COUNTERFACTUAL (parallel storage, never modifying canonical truth)
- A comparison baseline for learning — not a verdict

Counterfactual output is NOT:
- Evidence of a trading mistake
- Proof that a different approach "would have worked"
- An optimization recommendation
- A prediction of future performance
- Generated or modified by an LLM (Law #9 — deterministic Python only)

## Enforcement Mechanism

This skill is constitutional — it applies to ALL outputs by all mentor profiles
that reference counterfactual outcomes. Violation patterns:

- Any ASSERTION about what "should" have been done differently
- Any certainty claim about alternative exit outcomes without truth_mode framing
- Any ranking of counterfactual scenarios by outcome
- Any claim that simulation results apply to future trades

When in doubt: describe, don't prescribe. Report the number, frame the uncertainty,
stop before recommending.
