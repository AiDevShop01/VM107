---
name: citation-discipline
description: >
  Constitutional citation governance for all Phase 60 mentor profiles.
  Enforces [ref:<registry_id>:<field>] grammar on every ASSERTION sentence.
  Load this skill before any cognition that emits narrative sentences.
version: "1.0.0"
tags: [citation, governance, constitutional, phase-60]
trigger_patterns:
  - "emit narrative"
  - "write critique"
  - "produce analysis"
  - "generate summary"
allowed_tools:
  - skills_tool
---

# Citation Discipline

## Invariant

Every ASSERTION sentence MUST contain at least one citation token of the form:

```
[ref:<registry_id>:<field>]
[ref:<registry_id>:<field>@frame_<line_index>]
```

Where `<registry_id>` is a globally unique identifier from `VM107/registry/` (tool/, signal/, replay_template/, event_type/, behavioral_pattern/).

**Unknown `<registry_id>` → hard-fail.** The orchestrator will reject the narrative. No exceptions.

## Sentence Classification

Every sentence in the writer output must carry exactly one of four class labels:

| Class | Description | Citation Required |
|-------|-------------|-------------------|
| `ASSERTION` | Factual / behavioral / structural / causal / analytical claim about the trade | YES — at least one `[ref:...]` |
| `TRANSITION` | Connective or framing sentence; introduces or links ASSERTIONs | No |
| `SUMMARY` | Recap or rollup. Cannot contain uncited factual claims | No (but no bare assertions either) |
| `META` | Narrative-about-the-narrative (version stamp, profile info) | Forbidden — META must never cite |

**Rules:**
- An ASSERTION without any `[ref:...]` token → orchestrator hard-fails the narrative.
- A META sentence with any `[ref:...]` token → orchestrator hard-fails the narrative.
- A SUMMARY that embeds an assertion-shaped factual claim without a citation → orchestrator hard-fails.
- Compound claims must be split across sentences so each citation is attributable to exactly one claim.

## Citation Examples

**Valid ASSERTION:**
> "The trader delayed entry by `[ref:behavioral_analysis_tool:hesitation_seconds]` on this execution, exceeding the 3-second threshold defined in `[ref:behavioral_pattern:hesitation]`."

**Invalid ASSERTION (no citation — will be rejected):**
> "The trader hesitated before entry." ← REJECTED: bare assertion, no `[ref:...]`

**Behavioral claims must cite behavioral evidence specifically:**
- Use `[ref:behavioral_pattern:hesitation]` or `[ref:behavioral_analysis_tool:hesitation_seconds]`
- NOT `[ref:replay_line:abc-123]` — replay refs are structural, not behavioral evidence

**Frame anchor (optional, for replay line-level citations):**
> "Price broke the prior high at `[ref:replay_line:abc-123@frame_42]`."

## If You Cannot Cite a Claim

If you cannot find a registry-resolvable citation for an ASSERTION:

1. **Reclassify as TRANSITION** if the sentence is contextual framing rather than a factual claim.
2. **Omit the sentence entirely** — uncited ASSERTION is worse than a shorter narrative.
3. **Do NOT emit a bare ASSERTION** hoping the orchestrator will be lenient. It will not be.

After two bounded retries, the orchestrator applies `auto_bracket_unsourced` and the narrative is flagged for shadow-mode review. The goal is zero `[UNSOURCED]` sentences per narrative.
