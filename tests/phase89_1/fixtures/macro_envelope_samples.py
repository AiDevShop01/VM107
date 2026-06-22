"""Captured envelope shape fixtures for Phase 89.1 Plan 01 fence-block extraction tests.

These fixtures mirror real model output shapes observed during the 08:43 UTC dev test
where macro_investigator emits "prose followed by ```json fenced envelope" answers.

The bug being fixed: api_message.py called json.loads(answer_text) on the full text,
which fails because the prose preamble makes it invalid JSON — so citations[] stayed
empty and the hallucination gate could not be reviewed (REQ-89-9.1).

See: .planning/phases/89-macro-intelligence-workbench-investigation-counterfactual-
     contradiction-discovery/89-WIRING-RCA-HANDOFF.md (Gap #1)
"""

# ---------------------------------------------------------------------------
# Happy-path fixtures — parser should extract envelope and strip it from prose
# ---------------------------------------------------------------------------

PROSE_PLUS_FENCED_JSON = """\
The March 2024 CPI release [ref:release:CPIAUCSL-2024-03] showed headline inflation
at 3.5% YoY, beating consensus expectations of 3.4%. The repricing event \
[ref:belief:repricing-mar2024] that followed pushed the front end of the rates curve
materially higher as markets revised their Fed cut expectations.

Core PCE [ref:release:PCEPI-2024-03] has been more stubborn than headline CPI,
suggesting the disinflationary path remains bumpy heading into Q2 2024.

```json
{
  "answer": "The March 2024 CPI release showed headline inflation at 3.5% YoY, beating consensus expectations of 3.4%. The repricing event that followed pushed the front end of the rates curve materially higher as markets revised their Fed cut expectations.",
  "citations": [
    {"kind": "release", "id": "CPIAUCSL-2024-03", "label": "CPI March 2024 — BLS"},
    {"kind": "belief", "id": "repricing-mar2024", "label": "Fed repricing event Mar 2024"},
    {"kind": "release", "id": "PCEPI-2024-03", "label": "Core PCE March 2024 — BEA"}
  ],
  "b5_result": {"score": 0.83, "verdict": "accept"},
  "degraded": false,
  "blocking_contradiction_refusal": false,
  "truncated_at": null
}
```"""

PROSE_PLUS_FENCED_JSON_UPPERCASE = """\
Inflation data [ref:release:CPIAUCSL-2024-03] from Q1 2024 confirms the Federal
Reserve's "higher for longer" stance was justified. The belief shift \
[ref:belief:repricing-mar2024] in March contributed to a material repricing of
Treasury yields.

```JSON
{
  "answer": "Inflation data from Q1 2024 confirms the Federal Reserve's higher for longer stance was justified.",
  "citations": [
    {"kind": "release", "id": "CPIAUCSL-2024-03", "label": "CPI March 2024 — BLS"},
    {"kind": "belief", "id": "repricing-mar2024", "label": "Fed repricing event Mar 2024"}
  ],
  "b5_result": {"score": 0.77, "verdict": "accept"},
  "degraded": false,
  "blocking_contradiction_refusal": false,
  "truncated_at": null
}
```"""

PROSE_PLUS_FENCED_NO_LANG = """\
The labor market [ref:release:UNRATE-2024-03] remained resilient in March 2024
with unemployment at 3.8%. Wage growth [ref:belief:wages-sticky-h1-2024] continues
to run above the level consistent with 2% PCE inflation.

```
{
  "answer": "The labor market remained resilient in March 2024 with unemployment at 3.8%.",
  "citations": [
    {"kind": "release", "id": "UNRATE-2024-03", "label": "Unemployment Rate March 2024"},
    {"kind": "belief", "id": "wages-sticky-h1-2024", "label": "Sticky wage growth H1 2024"}
  ],
  "b5_result": {"score": 0.71, "verdict": "accept"},
  "degraded": false,
  "blocking_contradiction_refusal": false,
  "truncated_at": null
}
```"""

# ---------------------------------------------------------------------------
# Backward-compat fixture — bare JSON with no prose prefix (pre-89.1 happy path)
# ---------------------------------------------------------------------------

BARE_JSON_NO_FENCE = """\
{
  "answer": "The March 2024 CPI release confirmed the disinflationary path remains intact.",
  "citations": [
    {"kind": "release", "id": "CPIAUCSL-2024-03", "label": "CPI March 2024 — BLS"},
    {"kind": "belief", "id": "repricing-mar2024", "label": "Fed repricing event Mar 2024"}
  ],
  "b5_result": {"score": 0.90, "verdict": "accept"},
  "degraded": false,
  "blocking_contradiction_refusal": false,
  "truncated_at": null
}"""

# ---------------------------------------------------------------------------
# Failure-mode fixtures — parser should return (full_text, None) with no leakage
# ---------------------------------------------------------------------------

NO_FENCE_NO_JSON = """\
Based on the available macro data, the Federal Reserve appears to be nearing
the end of its hiking cycle. Core PCE has been trending lower for three consecutive
months and labor market slack is beginning to emerge in the household survey data.

No structured citations are available for this query — please consult the
release calendar directly."""

UNCLOSED_FENCE = """\
The Q1 2024 GDP release [ref:release:GDPC1-2024-Q1] came in above consensus at 1.6%
annualised. Inventory drawdowns and net exports dragged on the headline number.

```json
{
  "answer": "Q1 GDP came in at 1.6% annualised.",
  "citations": [
    {"kind": "release", "id": "GDPC1-2024-Q1", "label": "Real GDP Q1 2024"}
  ],
  "b5_result": {"score": 0.68, "verdict": "accept"},
  "degraded": false"""
# NOTE: deliberately missing the closing ``` to test unclosed-fence handling

FENCE_MALFORMED_JSON = """\
Monetary policy expectations [ref:belief:cuts-delayed-2024] shifted significantly
after the March CPI print [ref:release:CPIAUCSL-2024-03] surprised to the upside.

```json
{
  "answer": "Monetary policy expectations shifted after the March CPI surprise.",
  "citations": [
    {"kind": "belief", "id": "cuts-delayed-2024", "label": "Cut expectations delayed"},
    {"kind": "release", "id": "CPIAUCSL-2024-03", "label": "CPI March 2024"},
  ],
  "b5_result": {"score": 0.79, "verdict": "accept"},
  "degraded": false,
  "blocking_contradiction_refusal": false,
  "truncated_at": null
}
```"""
# NOTE: trailing comma after last citations entry makes this invalid JSON

# ---------------------------------------------------------------------------
# Phase 89.1 Plan 05 regression fixture — trailing extra closing brace
# Observed in v7 UAT batch: deepseek-v4-flash intermittently emits an extra `}`
# after the well-formed JSON object (~25% of questions in the v7 run).
# The parser's original `json.loads(stripped)` call raised JSONDecodeError on
# this shape, returning (raw_blob, None) and leaking the JSON into answer field.
# ---------------------------------------------------------------------------

BARE_JSON_TRAILING_EXTRA_BRACE = (
    '{"answer": "The September 2023 FOMC held rates, but the dot plot and SEP pushed the'
    " 'higher for longer' narrative aggressively: the median 2024 rate projection rose,"
    ' signaling fewer cuts. This repriced term premiums higher.",'
    ' "citations": ['
    '{"citation_id": "history:CPIAUCSL-hike-regime",'
    ' "source": "vm102.indicator_history (CPIAUCSL, 5Y range)",'
    ' "snippet": "CPIAUCSL 5Y series with rate-hike overlays."},'
    '{"citation_id": "release:CPIAUCSL-2022-06",'
    ' "source": "vm102.indicator_history",'
    ' "snippet": "CPIAUCSL June 2022 value = 294.957 (peak of hiking cycle, ~9.1% YoY)."}],'
    ' "degraded": true, "blocking_contradiction_refusal": false}\n}'
    # NOTE: trailing \n} after the well-formed JSON object — this is the LLM generation artifact
    # that caused json.loads() to fail in the v7 UAT batch (5/20 questions affected)
)

# ---------------------------------------------------------------------------
# Phase 89.1 Plan 05 regression fixture — double-encoded JSON quotes
# Observed in v8 UAT batch: deepseek-v4-flash intermittently emits \\" (literal
# backslash + quote) inside JSON string values instead of \" (the correct JSON
# escape). This causes json.loads() to see a bare " that prematurely terminates
# the string → JSONDecodeError: "Unterminated string" → envelope=None → leakage.
#
# Affected in v8 batch: Q1, Q5, Q11 (3/20 questions).
# The raw text ends with: `\\"blocking_contradiction_refusal\\": false}`
# where the `\\"` before `blocking` terminates the answer string early.
# ---------------------------------------------------------------------------

# Construct a string that has the two-character sequence backslash+quote (\")
# embedded inside the JSON answer value — this mimics the LLM artifact where
# the model emits double-backslash+quote (\\\") in the serialised text.
# In Python source: '\\\\\"' is the four-char sequence \\\" (two backslashes + quote).
# In the actual string value: \\" (backslash + backslash + quote).
# In a JSON parser's view: \\ → one literal backslash, " → closes the string.
_DOUBLE_ENCODED_ANSWER = (
    'The September 2023 FOMC meeting concluded with rates on hold, but the'
    ' \\\\"higher for longer\\\\" guidance embedded in the dot plot repriced'
    ' front-end Treasury yields significantly higher.'
)

BARE_JSON_DOUBLE_ENCODED_QUOTES = (
    '{"answer": "' + _DOUBLE_ENCODED_ANSWER + '",'
    ' "citations": ['
    '{"citation_id": "history:FEDFUNDS-hike-regime",'
    ' "source": "vm102.indicator_history (FEDFUNDS, 3Y range)",'
    ' "snippet": "FEDFUNDS 3Y series showing 2022-2023 hiking cycle."},'
    '{"citation_id": "release:FEDFUNDS-2023-09",'
    ' "source": "vm102.indicator_history",'
    ' "snippet": "FEDFUNDS Sep 2023 = 5.33% (peak of hiking cycle)."}],'
    ' "degraded": false, "blocking_contradiction_refusal": false}'
)
# NOTE: the \\\" sequences inside the answer string will cause json.loads() to fail
# with "Unterminated string" because json sees \\ → literal backslash, then
# " → string termination. The fix (step 4b in parse_macro_envelope) repairs this
# by replacing \\" with \" before retrying raw_decode.
