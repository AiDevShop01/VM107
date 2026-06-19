"""Phase 88.1 Plan 08 — indicator_enrichment_agent.

VM107 write-time Pydantic gate agent for AI enrichment of economic indicators.

Architecture decisions (CONTEXT.md + Plan 08):
- Layer 2 of the 3-layer AI Description architecture.
- Pydantic write-time gate: IndicatorEnrichment.model_validate() on every LLM output.
- Retry-once-then-fail per Phase 38 pattern: retries once on ValidationError,
  raises on second failure so caller falls back to curator Layer 1.
- Token budget: TOKEN_BUDGET_HARD (1500) * 4 chars used as rough char→token proxy.
  If narrative text exceeds this, treats as a budget violation and retries.
- raw_text forbidden: _parse() drops it before validation (Pydantic extra='forbid'
  would reject it anyway, but we drop it explicitly to give retry a chance).
- DO NOT call live LLM APIs during testing — llm_client is injected via __init__.

Hard flow:
  1. Build prompt (retry=False on attempt 1, retry=True on attempt 2).
  2. Call llm_client.complete(prompt, max_tokens=TOKEN_BUDGET_HARD).
  3. Parse JSON; drop raw_text if present.
  4. Augment dict with envelope fields (indicator_id, generated_at, version, model, prompt_version).
  5. IndicatorEnrichment.model_validate(output_dict).
  6. Token budget check (char proxy): if oversized → continue to next attempt.
  7. On ValidationError or budget violation: log + continue loop.
  8. After 2 attempts: raise last error.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

from pydantic import ValidationError

log = logging.getLogger(__name__)

# Import the Pydantic contract.
# In production VM107 fingpt_core is installed as a package.
# In dev/test the caller is responsible for adding fingpt_core to sys.path.
try:
    from fingpt_core.contracts.indicator_enrichment import (
        IndicatorEnrichment,
        TOKEN_BUDGET_HARD,
        TOKEN_BUDGET_SOFT,
    )
except ImportError:
    # Fallback: attempt relative path insertion for local dev without full install
    import sys as _sys
    import pathlib as _pathlib
    _core_path = str(_pathlib.Path(__file__).parents[5] / 'Dagster' / 'fingpt_core' / 'src')
    if _core_path not in _sys.path:
        _sys.path.insert(0, _core_path)
    from fingpt_core.contracts.indicator_enrichment import (
        IndicatorEnrichment,
        TOKEN_BUDGET_HARD,
        TOKEN_BUDGET_SOFT,
    )

from agents.indicator_enrichment_agent.prompt import build_prompt, PROMPT_VERSION

# Rough character-to-token approximation factor (4 chars ≈ 1 token for English)
_CHARS_PER_TOKEN = 4
# Budget violation threshold: hard token budget translated to chars
_HARD_BUDGET_CHARS = TOKEN_BUDGET_HARD * _CHARS_PER_TOKEN

# Number of attempts (initial + 1 retry per Phase 38 pattern)
_MAX_ATTEMPTS = 2


class IndicatorEnrichmentAgent:
    """VM107 indicator enrichment agent with Pydantic write-time gate.

    Generates IndicatorEnrichment AI layer for an economic indicator.
    Enforces the 3-layer contract (Curator / AI / Runtime Composition).

    Usage:
        agent = IndicatorEnrichmentAgent(llm_client=<client>)
        enrichment = agent.invoke('CPIAUCSL', curator_layer_dict)

    The llm_client must implement:
        .complete(prompt: str, max_tokens: int) -> str
    """

    agent_id = 'vm107_indicator_enrichment_agent'
    prompt_version = PROMPT_VERSION

    def __init__(self, llm_client=None):
        self.llm_client = llm_client  # injected; concrete client from registry resolution
        # Model identifier from env or registry (env-driven config, no hardcoded fallback)
        self.model = os.environ.get('INDICATOR_ENRICHMENT_MODEL') or 'claude-sonnet-x'

    def invoke(self, indicator_id: str, curator_layer: dict) -> IndicatorEnrichment:
        """Generate and validate an IndicatorEnrichment for the given indicator.

        Args:
            indicator_id:   Canonical indicator code (e.g. 'CPIAUCSL').
            curator_layer:  Layer 1 curator metadata dict (loaded from YAML by caller).

        Returns:
            Validated IndicatorEnrichment instance (frozen=True).

        Raises:
            ValidationError: If both attempts fail Pydantic validation.
            ValueError: If both attempts exceed the hard token budget.
            json.JSONDecodeError: If LLM output cannot be parsed as JSON on both attempts.
            RuntimeError: If llm_client is not set.
        """
        if self.llm_client is None:
            raise RuntimeError(
                'IndicatorEnrichmentAgent.llm_client is not set. '
                'Inject a concrete LLM client before calling invoke().'
            )

        last_err: Exception | None = None

        for attempt in range(1, _MAX_ATTEMPTS + 1):
            is_retry = attempt > 1
            prompt = build_prompt(indicator_id, curator_layer, retry=is_retry)

            # LLM call — caller supplies max_tokens = TOKEN_BUDGET_HARD
            raw_output: str = self.llm_client.complete(prompt, max_tokens=TOKEN_BUDGET_HARD)

            # Parse JSON and drop any forbidden raw_text field
            try:
                output_dict = self._parse(raw_output)
            except (json.JSONDecodeError, ValueError) as parse_err:
                log.warning(
                    'attempt %d/%d: JSON parse error for %s: %s',
                    attempt, _MAX_ATTEMPTS, indicator_id, parse_err,
                )
                last_err = parse_err
                continue

            # Augment with envelope fields that the LLM does not supply
            output_dict.update({
                'indicator_id': indicator_id,
                'generated_at': datetime.now(timezone.utc),
                'version': 1,
                'model': self.model,
                'prompt_version': self.prompt_version,
            })

            # Pydantic write-time gate
            try:
                envelope = IndicatorEnrichment.model_validate(output_dict)
            except ValidationError as ve:
                log.warning(
                    'attempt %d/%d: Pydantic validation failed for %s: %s',
                    attempt, _MAX_ATTEMPTS, indicator_id, ve,
                )
                last_err = ve
                continue

            # Token budget check (char proxy for total narrative volume)
            total_chars = (
                len(envelope.current_narrative)
                + len(envelope.trading_implications)
                + len(envelope.recent_changes)
            )
            if total_chars > _HARD_BUDGET_CHARS:
                budget_err = ValueError(
                    f'Hard token budget exceeded for {indicator_id}: '
                    f'{total_chars} chars > {_HARD_BUDGET_CHARS} limit'
                )
                log.warning(
                    'attempt %d/%d: %s', attempt, _MAX_ATTEMPTS, budget_err,
                )
                last_err = budget_err
                continue

            # All checks passed
            return envelope

        # Both attempts failed
        raise last_err or RuntimeError(
            f'IndicatorEnrichmentAgent failed for {indicator_id} without a specific error'
        )

    @staticmethod
    def _parse(raw_output: str) -> dict:
        """Parse LLM JSON output and sanitize before Pydantic validation.

        Drops the forbidden raw_text field if the LLM emits it. This gives
        the retry loop a chance to succeed when the LLM includes raw_text
        alongside the valid required fields.

        Args:
            raw_output: Raw string from the LLM.

        Returns:
            Parsed dict with raw_text removed (if present).

        Raises:
            json.JSONDecodeError: If output cannot be parsed as JSON.
        """
        data = json.loads(raw_output)
        if not isinstance(data, dict):
            raise ValueError(f'Expected dict from LLM; got {type(data).__name__}')
        if 'raw_text' in data:
            log.warning(
                '_parse: LLM emitted forbidden raw_text field — dropping before validation'
            )
            data.pop('raw_text')
        return data
