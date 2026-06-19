"""Phase 88.1 Plan 08 — indicator_enrichment_agent prompt template.

Locked decisions (CONTEXT.md):
- AI owns current_narrative, trading_implications, recent_changes, confidence.
- Curator owns: name, unit, source agency, short_description, why_it_matters.
- raw_text is FORBIDDEN — prompt instructs the LLM to return flat JSON only.
- Token budget: 1200 soft (triggers summarisation re-prompt), 1500 hard.

Prompt version: 88.1.0
"""
from __future__ import annotations

PROMPT_VERSION = '88.1.0'

INSTRUCTIONS = """You are a macro intelligence agent. You are given an economic indicator's
curator metadata (permanent facts: name, category, why it matters, affected assets).

Your task is to generate a current AI enrichment for this indicator based on the latest
macro environment understanding. Return ONLY a JSON object with exactly these 4 keys:
  current_narrative  — current conditions for this indicator (max 1200 characters)
  trading_implications — how current dynamics affect relevant markets (max 1200 characters)
  recent_changes — what has changed in the most recent release/revision cycle (max 1200 characters)
  confidence — your confidence in this enrichment quality as a float between 0.0 and 1.0

CRITICAL RULES:
1. Do NOT include a raw_text field. The downstream validator forbids it.
2. Do NOT include any other fields beyond the 4 listed above.
3. Keep each field under 1200 characters. Concise is better than verbose.
4. Return ONLY the JSON object — no markdown, no preamble, no explanation.
"""

RETRY_SUFFIX = (
    '\n\nPrior attempt failed validation or exceeded token budget. '
    'Be MORE CONCISE. Keep every field under 800 characters. '
    'Return ONLY the JSON object with the 4 required keys.'
)


def build_prompt(indicator_id: str, curator_layer: dict, retry: bool = False) -> str:
    """Build the enrichment prompt for a given indicator.

    Args:
        indicator_id:   Canonical indicator code (e.g. CPIAUCSL).
        curator_layer:  Layer 1 curator metadata dict.
        retry:          True if this is the second attempt (adds conciseness instruction).

    Returns:
        Full prompt string ready for the LLM.
    """
    curator_summary = '\n'.join(
        f'  {k}: {v}'
        for k, v in curator_layer.items()
        if v is not None
    )

    prompt = (
        f'{INSTRUCTIONS}\n\n'
        f'Indicator ID: {indicator_id}\n'
        f'Curator Layer (Layer 1 — permanent facts, do NOT restate verbatim):\n'
        f'{curator_summary}\n\n'
        f'Generate the 4-field JSON enrichment now:'
    )

    if retry:
        prompt += RETRY_SUFFIX

    return prompt
