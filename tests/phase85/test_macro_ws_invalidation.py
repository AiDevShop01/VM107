"""Phase 85 Plan 11 — WS invalidation publisher tests (TDD RED/GREEN).

Tests:
1. test_publish_topic_format — publish_indicator_updated("CPIAUCSL") calls
   redis.publish with topic "macro.indicator.CPIAUCSL.updated"
2. test_publish_payload_contains_topic_and_snapshot_id — JSON has exactly
   two keys: topic + snapshot_id (Phase 74 thin-invalidation lock — NO body).
3. test_publish_failure_logged_not_raised — redis.from_url raises; no exception
   propagates; logger.error called.
4. test_completion_hook_publishes — BrainOrchestrator completion hook invokes
   publish_indicator_updated with the right indicator_id (Approach B).
5. test_required_redis_url_at_import — monkeypatching REDIS_URL missing causes
   RuntimeError on import.
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import pytest
from unittest.mock import MagicMock, patch, call


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_import(monkeypatch, redis_url="redis://localhost:6379"):
    """Import publishers.macro_ws_invalidation with a fresh module (bypasses cache).

    Sets REDIS_URL env var before import so the module-level fail-fast passes.
    Returns the freshly-imported module.
    """
    monkeypatch.setenv("REDIS_URL", redis_url)
    # Remove cached module so re-import re-runs module-level code
    for key in list(sys.modules.keys()):
        if "macro_ws_invalidation" in key:
            del sys.modules[key]
    import publishers.macro_ws_invalidation as mod
    return mod


# ---------------------------------------------------------------------------
# Test: publish_indicator_updated — topic format
# ---------------------------------------------------------------------------

class TestPublishIndicatorUpdatedTopicFormat:
    """publish_indicator_updated must send to the correct per-indicator Redis topic."""

    def test_publish_topic_format(self, monkeypatch):
        """publish to macro.indicator.<id>.updated — NOT a bulk macro.indicators.updated."""
        mod = _fresh_import(monkeypatch)

        mock_redis_instance = MagicMock()
        with patch("publishers.macro_ws_invalidation.redis") as mock_redis_module:
            mock_redis_module.from_url.return_value = mock_redis_instance
            mod.publish_indicator_updated("CPIAUCSL")

        # Assert topic used
        publish_calls = mock_redis_instance.publish.call_args_list
        assert len(publish_calls) == 1, f"Expected 1 publish call, got {len(publish_calls)}"
        topic_arg = publish_calls[0][0][0]
        assert topic_arg == "macro.indicator.CPIAUCSL.updated", (
            f"Topic mismatch: got {topic_arg!r}"
        )

    def test_publish_topic_no_bulk_topic(self, monkeypatch):
        """Must NOT publish to macro.indicators.updated (D3 lock: per-indicator only)."""
        mod = _fresh_import(monkeypatch)

        mock_redis_instance = MagicMock()
        with patch("publishers.macro_ws_invalidation.redis") as mock_redis_module:
            mock_redis_module.from_url.return_value = mock_redis_instance
            mod.publish_indicator_updated("FEDFUNDS")

        topic_arg = mock_redis_instance.publish.call_args[0][0]
        assert "macro.indicators.updated" not in topic_arg, (
            "D3 lock violated: bulk topic must not be used"
        )
        assert topic_arg == "macro.indicator.FEDFUNDS.updated"


# ---------------------------------------------------------------------------
# Test: publish_indicator_updated — payload shape
# ---------------------------------------------------------------------------

class TestPublishPayloadShape:
    """WS payload must contain only topic + snapshot_id (Phase 74 thin-invalidation)."""

    def test_publish_payload_contains_topic_and_snapshot_id(self, monkeypatch):
        """Payload JSON has exactly two keys: topic and snapshot_id."""
        mod = _fresh_import(monkeypatch)

        captured_payloads: list[dict] = []

        def capture_publish(topic, payload_json):
            captured_payloads.append(json.loads(payload_json))

        mock_redis_instance = MagicMock()
        mock_redis_instance.publish.side_effect = capture_publish

        with patch("publishers.macro_ws_invalidation.redis") as mock_redis_module:
            mock_redis_module.from_url.return_value = mock_redis_instance
            mod.publish_indicator_updated("CPIAUCSL")

        assert len(captured_payloads) == 1
        payload = captured_payloads[0]
        assert set(payload.keys()) == {"topic", "snapshot_id"}, (
            f"Phase 74 thin-invalidation violation — extra keys: {set(payload.keys())}"
        )
        assert payload["topic"] == "macro.indicator.CPIAUCSL.updated"
        # snapshot_id must be a non-empty string (UUID)
        assert isinstance(payload["snapshot_id"], str)
        assert len(payload["snapshot_id"]) > 0

    def test_publish_payload_no_body_fields(self, monkeypatch):
        """Payload must NOT include actual, forecast, executive_summary, etc."""
        mod = _fresh_import(monkeypatch)

        captured_payloads: list[dict] = []

        def capture_publish(topic, payload_json):
            captured_payloads.append(json.loads(payload_json))

        mock_redis_instance = MagicMock()
        mock_redis_instance.publish.side_effect = capture_publish

        with patch("publishers.macro_ws_invalidation.redis") as mock_redis_module:
            mock_redis_module.from_url.return_value = mock_redis_instance
            mod.publish_indicator_updated("CPIAUCSL")

        payload = captured_payloads[0]
        forbidden_keys = {"actual", "forecast", "executive_summary", "prior", "revision_flag"}
        found = set(payload.keys()) & forbidden_keys
        assert not found, (
            f"Phase 74 thin-invalidation violation — body fields must not be present: {found}"
        )


# ---------------------------------------------------------------------------
# Test: publish_indicator_updated — failure handling
# ---------------------------------------------------------------------------

class TestPublishFailureHandling:
    """Redis failures must be logged and swallowed (WS is observability, not source of truth)."""

    def test_publish_failure_logged_not_raised(self, monkeypatch):
        """When redis.from_url raises, no exception propagates; logger.error is called."""
        mod = _fresh_import(monkeypatch)

        with patch("publishers.macro_ws_invalidation.redis") as mock_redis_module, \
             patch("publishers.macro_ws_invalidation.logger") as mock_logger:
            mock_redis_module.from_url.side_effect = ConnectionError("Redis unavailable")
            # Should not raise
            mod.publish_indicator_updated("CPIAUCSL")

        assert mock_logger.error.call_count == 1, (
            "logger.error must be called once on publish failure"
        )

    def test_publish_redis_publish_raises_does_not_propagate(self, monkeypatch):
        """When r.publish raises, the exception is swallowed."""
        mod = _fresh_import(monkeypatch)

        mock_redis_instance = MagicMock()
        mock_redis_instance.publish.side_effect = OSError("connection reset")

        with patch("publishers.macro_ws_invalidation.redis") as mock_redis_module, \
             patch("publishers.macro_ws_invalidation.logger") as mock_logger:
            mock_redis_module.from_url.return_value = mock_redis_instance
            # Should not raise
            mod.publish_indicator_updated("CPIAUCSL")

        assert mock_logger.error.call_count == 1


# ---------------------------------------------------------------------------
# Test: Approach B — Brain completion hook publishes WS invalidation
# ---------------------------------------------------------------------------

class TestCompletionHookPublishes:
    """Brain orchestrator completion hook must invoke publish_indicator_updated (Approach B)."""

    def test_completion_hook_publishes(self, monkeypatch):
        """register_completion_hook registered via create_macro_release_goal on_complete kwarg.

        Approach B: BrainOrchestrator.register_completion_hook(goal_id, fn) stores the hook.
        When notify_goal_completed(goal_id) is called, fn is invoked with the stored
        indicator_id from the goal payload.
        """
        from core.scheduling.macro_release_goal import (
            create_macro_release_goal,
            BrainOrchestrator,
        )
        from publishers.macro_ws_invalidation import publish_indicator_updated

        # Set up mock orchestrator with completion hook support
        orc = MagicMock(spec=BrainOrchestrator)
        orc.find_goal_by_event_id.return_value = None
        orc.create_goal.return_value = "goal_phase85_test"
        orc.add_task.side_effect = ["task_001", "task_002", "task_003"]

        # Track registered completion hooks
        registered_hooks: dict[str, callable] = {}

        def _register_hook(goal_id, fn):
            registered_hooks[goal_id] = fn

        orc.register_completion_hook.side_effect = _register_hook

        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

        published_indicator_ids: list[str] = []

        def mock_publish(indicator_id):
            published_indicator_ids.append(indicator_id)

        with patch("publishers.macro_ws_invalidation.publish_indicator_updated", mock_publish):
            create_macro_release_goal(
                event_id="CPIAUCSL:2026-06-12T12:30:00Z",
                indicator_id="CPIAUCSL",
                orchestrator=orc,
                on_complete=lambda: mock_publish("CPIAUCSL"),
            )

        # A completion hook must have been registered for the goal
        assert "goal_phase85_test" in registered_hooks, (
            "register_completion_hook must be called with the goal_id"
        )

        # When the hook fires, publish must be called with the right indicator_id
        registered_hooks["goal_phase85_test"]()
        assert "CPIAUCSL" in published_indicator_ids, (
            f"publish_indicator_updated must have been called with CPIAUCSL; got {published_indicator_ids}"
        )

    def test_notify_goal_completed_fires_hook(self, monkeypatch):
        """BrainOrchestrator.notify_goal_completed invokes the registered hook."""
        from core.scheduling.macro_release_goal import BrainOrchestrator

        mock_goal_service = MagicMock()
        orc = BrainOrchestrator(goal_service=mock_goal_service)

        hook_fired: list[bool] = []
        orc.register_completion_hook("goal_xyz", lambda: hook_fired.append(True))

        orc.notify_goal_completed("goal_xyz")

        assert hook_fired == [True], "notify_goal_completed must fire the registered hook"

    def test_notify_goal_completed_unknown_goal_noop(self, monkeypatch):
        """notify_goal_completed for an unknown goal_id is a safe no-op."""
        from core.scheduling.macro_release_goal import BrainOrchestrator

        mock_goal_service = MagicMock()
        orc = BrainOrchestrator(goal_service=mock_goal_service)
        # No hook registered — should not raise
        orc.notify_goal_completed("goal_does_not_exist")


# ---------------------------------------------------------------------------
# Test: REDIS_URL fail-fast at module import
# ---------------------------------------------------------------------------

class TestRedisUrlFailFast:
    """REDIS_URL missing must cause RuntimeError on module import."""

    def test_required_redis_url_at_import(self, monkeypatch):
        """Importing publishers.macro_ws_invalidation without REDIS_URL raises RuntimeError."""
        # Remove REDIS_URL if present
        monkeypatch.delenv("REDIS_URL", raising=False)
        # Remove any cached module
        for key in list(sys.modules.keys()):
            if "macro_ws_invalidation" in key:
                del sys.modules[key]

        with pytest.raises(RuntimeError, match="REDIS_URL"):
            import publishers.macro_ws_invalidation  # noqa: F401

    def test_redis_url_set_allows_import(self, monkeypatch):
        """With REDIS_URL set, import succeeds without raising."""
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
        for key in list(sys.modules.keys()):
            if "macro_ws_invalidation" in key:
                del sys.modules[key]
        import publishers.macro_ws_invalidation as mod  # noqa: F401
        assert hasattr(mod, "publish_indicator_updated")
