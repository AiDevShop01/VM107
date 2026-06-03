"""Observation publisher tests — GREEN (Wave 1, Plan 01).

Verifies:
- publish_observation(obs) calls redis.publish('vm107.observations', obs.model_dump_json())
- env var VM107_SUPERVISORY_REDIS_URL resolved via _required helper at module import (fail-fast)
- invalid Observation (extra="forbid" violation) raises before publish
- connection failure raises (no silent swallow)
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from unittest import mock

import pytest

from fingpt_core.contracts.observation import Observation


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_obs(**kwargs) -> Observation:
    """Build a valid Observation for test use."""
    defaults = dict(
        category="supervisory",
        severity="WARNING",
        body="Test observation",
        generated_at=datetime(2026, 6, 3, 10, 0, 0, tzinfo=timezone.utc),
        source_vm="VM107",
    )
    defaults.update(kwargs)
    return Observation(**defaults)


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestPublishObservation:
    """publish_observation() sends Observation JSON to the vm107.observations channel."""

    def test_publishes_to_correct_channel(self):
        """publish_observation calls redis.publish on 'vm107.observations'."""
        import fakeredis

        obs = _make_obs()

        with mock.patch.dict(
            os.environ, {"VM107_SUPERVISORY_REDIS_URL": "redis://localhost:6379/0"}
        ):
            # Patch redis.from_url to return a fakeredis client
            fake_client = fakeredis.FakeRedis(decode_responses=True)
            with mock.patch("redis.from_url", return_value=fake_client):
                # Re-import to pick up the patched env var
                import importlib
                import services.observation_publisher as pub_mod
                importlib.reload(pub_mod)

                pub_mod.publish_observation(obs)

        # fakeredis doesn't support pubsub message inspection easily;
        # verify via a direct publish call count using a mock
        fake_client2 = mock.MagicMock()
        fake_client2.publish.return_value = 1

        with mock.patch.dict(
            os.environ, {"VM107_SUPERVISORY_REDIS_URL": "redis://localhost:6379/0"}
        ):
            with mock.patch("redis.from_url", return_value=fake_client2):
                import importlib
                import services.observation_publisher as pub_mod2
                importlib.reload(pub_mod2)

                result = pub_mod2.publish_observation(obs)

        fake_client2.publish.assert_called_once()
        call_args = fake_client2.publish.call_args
        channel = call_args[0][0]
        assert channel == "vm107.observations", (
            f"Expected channel 'vm107.observations', got {channel!r}"
        )

    def test_publishes_valid_json_matching_model_dump(self):
        """The published payload is obs.model_dump_json() — valid JSON, matches Observation shape."""
        obs = _make_obs(category="supervisory", severity="CRITICAL", body="Price at invalidation")
        fake_client = mock.MagicMock()
        fake_client.publish.return_value = 1

        with mock.patch.dict(
            os.environ, {"VM107_SUPERVISORY_REDIS_URL": "redis://localhost:6379/0"}
        ):
            with mock.patch("redis.from_url", return_value=fake_client):
                import importlib
                import services.observation_publisher as pub_mod
                importlib.reload(pub_mod)
                pub_mod.publish_observation(obs)

        call_args = fake_client.publish.call_args
        payload_str = call_args[0][1]

        # Must be valid JSON
        payload = json.loads(payload_str)

        # Must contain the key Observation fields
        assert payload["category"] == "supervisory"
        assert payload["severity"] == "CRITICAL"
        assert payload["body"] == "Price at invalidation"
        assert payload["source_vm"] == "VM107"
        assert "observation_id" in payload

    def test_returns_subscriber_count(self):
        """publish_observation returns the subscriber count from redis.publish."""
        obs = _make_obs()
        fake_client = mock.MagicMock()
        fake_client.publish.return_value = 3  # 3 subscribers

        with mock.patch.dict(
            os.environ, {"VM107_SUPERVISORY_REDIS_URL": "redis://localhost:6379/0"}
        ):
            with mock.patch("redis.from_url", return_value=fake_client):
                import importlib
                import services.observation_publisher as pub_mod
                importlib.reload(pub_mod)
                result = pub_mod.publish_observation(obs)

        assert result == 3

    def test_raises_on_non_observation_type(self):
        """Passing a non-Observation raises TypeError before publish."""
        fake_client = mock.MagicMock()

        with mock.patch.dict(
            os.environ, {"VM107_SUPERVISORY_REDIS_URL": "redis://localhost:6379/0"}
        ):
            with mock.patch("redis.from_url", return_value=fake_client):
                import importlib
                import services.observation_publisher as pub_mod
                importlib.reload(pub_mod)

                with pytest.raises(TypeError):
                    pub_mod.publish_observation({"category": "supervisory"})  # type: ignore[arg-type]

        # Redis publish must NOT have been called
        fake_client.publish.assert_not_called()

    def test_observation_extra_forbid_raises_at_construction(self):
        """Pydantic extra='forbid' raises ValidationError on unknown fields — before publish."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            Observation(
                category="supervisory",
                severity="WARNING",
                body="test",
                generated_at=datetime.now(timezone.utc),
                source_vm="VM107",
                unknown_field="bad",  # type: ignore[call-arg]
            )

    def test_connection_failure_raises(self):
        """Redis publish failure propagates — not silently swallowed."""
        obs = _make_obs()
        fake_client = mock.MagicMock()
        fake_client.publish.side_effect = ConnectionError("Redis connection refused")

        with mock.patch.dict(
            os.environ, {"VM107_SUPERVISORY_REDIS_URL": "redis://localhost:6379/0"}
        ):
            with mock.patch("redis.from_url", return_value=fake_client):
                import importlib
                import services.observation_publisher as pub_mod
                importlib.reload(pub_mod)

                with pytest.raises(ConnectionError):
                    pub_mod.publish_observation(obs)


class TestEnvVarResolution:
    """VM107_SUPERVISORY_REDIS_URL must be set — fail-fast at module load."""

    def test_missing_env_var_raises_at_module_load(self):
        """Module-level _required() raises RuntimeError when env var absent."""
        import sys

        # Remove cached module if present
        if "services.observation_publisher" in sys.modules:
            del sys.modules["services.observation_publisher"]

        # Ensure env var is NOT set
        env = {k: v for k, v in os.environ.items() if k != "VM107_SUPERVISORY_REDIS_URL"}

        with mock.patch.dict(os.environ, env, clear=True):
            with pytest.raises((RuntimeError, KeyError)):
                import services.observation_publisher  # noqa: F401 — import triggers fail-fast
