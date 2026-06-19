"""Phase 88.1 Plan 09 — Regenerate AI enrichment for 6 known-broken indicators.

Django management command: `python manage.py regenerate_indicator_enrichment`

Purpose:
    Re-runs the fixed (Pydantic + curator-fallback) generator from Plan 08 on
    exactly 6 indicators that are known to have unrecoverable AI descriptions:
      - 5 unrecoverable from 88-09: BUSLOANS, NONBORRES, PAYEMS, PCEPI, TEDRATE
      - 1 typo case: IRLTLT01EZM156N (what_it_is -> what_is_it typo now fixed)

Architecture:
    - This is a one-shot command (not a long-running listener/worker).
    - No docker-compose sibling service needed per CLAUDE.md rule.
    - Command invokes IndicatorEnrichmentAgent per indicator.
    - On agent success: persists via VM100 PUT endpoint (VM100_INTERNAL_API_URL).
    - On agent ValidationError/ValueError: logs warning, marks curator-only fallback.
    - Idempotent: re-running updates the same ai_enrichment column with new generated_at.
    - --dry-run: runs agent but skips _persist call (safe for testing).

DO NOT run this against live AI APIs in tests. The agent accepts an injected
llm_client, and tests mock IndicatorEnrichmentAgent.invoke directly.

Env vars required for _persist (production only):
    VM100_INTERNAL_API_URL  — base URL for VM100 internal API (no trailing slash)
"""
import logging
import yaml
from pathlib import Path
from pydantic import ValidationError

from agents.indicator_enrichment_agent.agent import IndicatorEnrichmentAgent

log = logging.getLogger(__name__)

# The 6-indicator target set for Phase 88.1 targeted regeneration.
# 5 unrecoverable from 88-09 + 1 typo case.
TARGET_INDICATORS = ['BUSLOANS', 'NONBORRES', 'PAYEMS', 'PCEPI', 'TEDRATE', 'IRLTLT01EZM156N']

# Curator YAML directory — resolve relative to this file's location.
# File is at: VM107/agents/indicator_enrichment_agent/management/commands/
# VM107 root is 4 parent steps up.
_THIS_DIR = Path(__file__).resolve().parent
_VM107_ROOT = (_THIS_DIR / '..' / '..' / '..' / '..').resolve()
CURATOR_DIR = _VM107_ROOT / 'config' / 'curator' / 'indicators'


try:
    from django.core.management.base import BaseCommand, CommandError
    _DJANGO_AVAILABLE = True
except ImportError:
    # Fallback for test environments without Django
    _DJANGO_AVAILABLE = False

    class BaseCommand:  # noqa: N801 (minimal shim)
        """Minimal shim for test environments without Django installed."""
        def __init__(self):
            import io
            self.stdout = io.StringIO()
            self.stderr = io.StringIO()
            self.style = _StyleShim()

        def handle(self, *args, **opts):
            raise NotImplementedError

    class CommandError(Exception):
        pass

    class _StyleShim:
        def SUCCESS(self, s):
            return s


class Command(BaseCommand):
    """Targeted regeneration of AI enrichment for 6 known-broken indicators.

    Closes the failure mode surfaced in Phase 88-09: unrecoverable AI descriptions
    and typo key (what_it_is -> what_is_it). Validates the Pydantic+curator-fallback
    fix from Plan 08 on the same indicators that broke it.
    """

    help = (
        'Regenerate AI enrichment for 6 known-broken indicators via the '
        'Pydantic-validated agent from Plan 08.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--indicators',
            type=str,
            default=','.join(TARGET_INDICATORS),
            help=(
                'Comma-separated indicator IDs to regenerate '
                f'(defaults to the 6-target set: {",".join(TARGET_INDICATORS)})'
            ),
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            default=False,
            help=(
                'Run agent.invoke for each indicator but skip _persist. '
                'Safe for testing — does not write to VM100 backend.'
            ),
        )

    def handle(self, *args, **opts):
        indicators = [i.strip() for i in opts['indicators'].split(',') if i.strip()]
        dry_run = opts.get('dry_run', False)

        if dry_run:
            self.stdout.write('[DRY RUN] Regenerating without persisting.')

        agent = IndicatorEnrichmentAgent()

        results = {
            'success': [],
            'curator_fallback': [],
            'system_error': [],
        }

        for indicator_id in indicators:
            curator_path = CURATOR_DIR / f'{indicator_id}.yaml'

            if not curator_path.exists():
                self.stderr.write(
                    f'[{indicator_id}] No curator YAML at {curator_path} — skipping'
                )
                results['system_error'].append(indicator_id)
                continue

            curator_layer = yaml.safe_load(curator_path.read_text(encoding='utf-8'))

            try:
                envelope = agent.invoke(indicator_id, curator_layer)
            except (ValidationError, ValueError) as exc:
                self.stderr.write(
                    f'[{indicator_id}] Agent failed ({type(exc).__name__}): {exc}; '
                    f'indicator will fall back to curator Layer 1 at render time'
                )
                results['curator_fallback'].append(indicator_id)
                continue
            except Exception as exc:  # noqa: BLE001
                self.stderr.write(
                    f'[{indicator_id}] Unexpected error: {exc}'
                )
                results['system_error'].append(indicator_id)
                continue

            if not dry_run:
                try:
                    self._persist(indicator_id, envelope)
                except Exception as exc:  # noqa: BLE001
                    self.stderr.write(
                        f'[{indicator_id}] Persist failed: {exc}'
                    )
                    results['system_error'].append(indicator_id)
                    continue

            results['success'].append(indicator_id)
            self.stdout.write(
                f'[{indicator_id}] {"(dry-run) " if dry_run else ""}enriched + '
                f'{"skipped persist" if dry_run else "persisted"}'
            )

        summary = (
            f"Done — success={results['success']} "
            f"curator_fallback={results['curator_fallback']} "
            f"system_error={results['system_error']}"
        )
        self.stdout.write(self.style.SUCCESS(summary))
        return results

    def _persist(self, indicator_id: str, envelope) -> None:
        """Persist enrichment envelope to VM100 via the internal PUT endpoint.

        Cross-VM write: VM107 -> VM100 backend.
        Idempotency: PUT /api/v2/enrichment/indicator/{id} uses update-or-create
        so re-running replaces the existing ai_enrichment column value.

        Env-driven config (no hardcoded URL, no fallback per CLAUDE.md directive):
            VM100_INTERNAL_API_URL must be set or this raises RuntimeError immediately.

        Args:
            indicator_id: Canonical indicator code (e.g. 'BUSLOANS').
            envelope:     Validated IndicatorEnrichment instance from agent.invoke().

        Raises:
            RuntimeError:   If VM100_INTERNAL_API_URL is not set.
            requests.HTTPError: If VM100 returns non-2xx.
        """
        import os
        import requests

        vm100_api = os.environ.get('VM100_INTERNAL_API_URL')
        if not vm100_api:
            raise RuntimeError(
                'VM100_INTERNAL_API_URL must be set (env-driven config lock: '
                'no fallback defaults per CLAUDE.md feedback_env_driven_no_fallbacks.md)'
            )

        url = f'{vm100_api.rstrip("/")}/api/v2/enrichment/indicator/{indicator_id}'
        payload = {'ai_enrichment': envelope.model_dump(mode='json')}

        resp = requests.put(url, json=payload, timeout=30)
        resp.raise_for_status()
        log.info('Persisted enrichment for %s — HTTP %s', indicator_id, resp.status_code)
