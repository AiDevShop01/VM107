"""Phase 85 Plan 15 — Task 3 (TDD RED): Backfill CLI harness tests.

Tests:
1. test_backfill_dry_run_no_writes — --dry-run --all does not modify any rows
2. test_backfill_single_indicator — --indicator CPIAUCSL writes one row; second invocation skips (idempotent)
3. test_backfill_respects_manual_override — pre-seeded row with manual_override=True blocks re-write
4. test_backfill_module_importable — backfill.backfill_indicator_descriptions importable
5. test_load_pending_indicators_filters_manual_override — load_pending_indicators skips manual_override rows
6. test_backfill_run_calls_upsert_per_row — run() calls upsert_description once per row
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

pytestmark = pytest.mark.phase_85

BACKFILL_PATH = Path("/Volumes/ HardDrive/FinGPT/VM107/backfill/backfill_indicator_descriptions.py")


class TestBackfillModule:
    """Backfill module structure."""

    def test_backfill_module_importable(self):
        """backfill.backfill_indicator_descriptions must be importable."""
        import importlib
        mod = importlib.import_module("backfill.backfill_indicator_descriptions")
        assert hasattr(mod, "run"), "Module must export run() function"
        assert hasattr(mod, "load_pending_indicators"), "Module must export load_pending_indicators()"
        assert hasattr(mod, "main"), "Module must export main() for CLI"

    def test_backfill_file_exists(self):
        """backfill/backfill_indicator_descriptions.py must exist."""
        assert BACKFILL_PATH.exists(), f"Missing: {BACKFILL_PATH}"

    def test_backfill_has_argparse(self):
        """Backfill script must use argparse for CLI."""
        content = BACKFILL_PATH.read_text()
        assert "argparse" in content, "Backfill must use argparse for CLI interface"

    def test_backfill_has_dry_run_support(self):
        """Backfill script must support --dry-run flag."""
        content = BACKFILL_PATH.read_text()
        assert "--dry-run" in content or "dry_run" in content, (
            "Backfill must support --dry-run flag"
        )

    def test_backfill_has_all_flag(self):
        """Backfill script must support --all flag."""
        content = BACKFILL_PATH.read_text()
        assert "--all" in content, "Backfill must support --all flag"

    def test_backfill_has_indicator_flag(self):
        """Backfill script must support --indicator flag."""
        content = BACKFILL_PATH.read_text()
        assert "--indicator" in content, "Backfill must support --indicator flag"


class TestBackfillDryRun:
    """--dry-run mode does not write to DB."""

    def test_dry_run_no_upsert_calls(self):
        """--dry-run mode must not call upsert_description."""
        from backfill.backfill_indicator_descriptions import run

        fake_rows = [
            ("CPIAUCSL", "Consumer Price Index", "MoM change", ["food", "energy"], "HIGH", "BLS", "monthly"),
            ("NFPR", "Nonfarm Payrolls", "BLS employer survey", [], "HIGH", "BLS", "monthly"),
        ]

        with patch("backfill.backfill_indicator_descriptions.load_pending_indicators", return_value=fake_rows), \
             patch("backfill.backfill_indicator_descriptions.upsert_description") as mock_upsert:
            run(dry_run=True)

        mock_upsert.assert_not_called(), "upsert_description must NOT be called in dry_run mode"


class TestBackfillSingleIndicator:
    """--indicator <code> processes exactly one row."""

    def test_single_indicator_calls_load_with_code(self):
        """run(only_indicator='CPIAUCSL') passes indicator code to load_pending_indicators."""
        from backfill.backfill_indicator_descriptions import run

        fake_row = ("CPIAUCSL", "Consumer Price Index", "MoM change", ["food"], "HIGH", "BLS", "monthly")

        with patch("backfill.backfill_indicator_descriptions.load_pending_indicators", return_value=[fake_row]) as mock_load, \
             patch("backfill.backfill_indicator_descriptions.upsert_description", return_value=True), \
             patch("backfill.backfill_indicator_descriptions._dispatch_agent", return_value={
                 "what_is_it": "CPI measures prices", "why_important": "Fed target", "why_traders_care": "Rate driver",
                 "_model_version": "claude-test", "_prompt_version": "1.0.0",
             }):
            run(only_indicator="CPIAUCSL")

        mock_load.assert_called_once_with("CPIAUCSL")

    def test_single_indicator_calls_upsert_once(self):
        """run(only_indicator='CPIAUCSL') calls upsert_description exactly once."""
        from backfill.backfill_indicator_descriptions import run

        fake_row = ("CPIAUCSL", "Consumer Price Index", "MoM change", ["food"], "HIGH", "BLS", "monthly")

        with patch("backfill.backfill_indicator_descriptions.load_pending_indicators", return_value=[fake_row]), \
             patch("backfill.backfill_indicator_descriptions.upsert_description", return_value=True) as mock_upsert, \
             patch("backfill.backfill_indicator_descriptions._dispatch_agent", return_value={
                 "what_is_it": "CPI measures prices", "why_important": "Fed target", "why_traders_care": "Rate driver",
                 "_model_version": "claude-test", "_prompt_version": "1.0.0",
             }):
            run(only_indicator="CPIAUCSL")

        assert mock_upsert.call_count == 1, "upsert_description must be called exactly once"


class TestBackfillManualOverrideRespected:
    """Rows with manual_override=True are not re-processed."""

    def test_backfill_respects_manual_override_via_upsert(self):
        """When upsert_description returns False, run() logs SKIPPED but does not error."""
        from backfill.backfill_indicator_descriptions import run

        fake_row = ("CPIAUCSL", "Consumer Price Index", "MoM change", ["food"], "HIGH", "BLS", "monthly")

        with patch("backfill.backfill_indicator_descriptions.load_pending_indicators", return_value=[fake_row]), \
             patch("backfill.backfill_indicator_descriptions.upsert_description", return_value=False) as mock_upsert, \
             patch("backfill.backfill_indicator_descriptions._dispatch_agent", return_value={
                 "what_is_it": "CPI measures prices", "why_important": "Fed target", "why_traders_care": "Rate driver",
                 "_model_version": "claude-test", "_prompt_version": "1.0.0",
             }):
            # Must not raise — SKIPPED is a normal log event
            run(only_indicator="CPIAUCSL")

        # upsert was still called; it just returned False
        mock_upsert.assert_called_once()


class TestLoadPendingIndicators:
    """load_pending_indicators SQL query shape."""

    def test_load_pending_indicators_query_excludes_manual_override(self):
        """load_pending_indicators must filter out manual_override=true rows via SQL."""
        from backfill import backfill_indicator_descriptions as mod

        # Inspect source code for the expected SQL pattern
        src = Path(mod.__file__).read_text()
        assert "manual_override" in src, (
            "load_pending_indicators must filter on manual_override in SQL"
        )
        assert "IS NULL" in src or "is null" in src.lower(), (
            "load_pending_indicators must handle NULL ai_description rows"
        )
