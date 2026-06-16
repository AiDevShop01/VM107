"""Phase 87 Wave 4a — backfill_macro_episodes idempotency + helper unit tests.

Per Phase 47.2 lock: VM107 MUST NOT read /cold-data or /mnt/parquet directly;
the backfill script pulls from the VM101 typed economic_event API. These tests
exercise the deterministic-episode-id helper + the Qdrant upsert idempotency
directly (the live HTTP call to VM101 is exercised in Plan 87-14 Wave 8 deploy).
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.phase_87


def _fake_releases(n=30, indicator_id="CPIAUCSL"):
    out = []
    for i in range(n):
        out.append({
            "release_id": str(uuid.uuid4()),
            "indicator_id": indicator_id,
            "release_date": (
                datetime.now(tz=timezone.utc) - timedelta(days=30 * i)
            ).isoformat(),
            "actual": 3.0 + i * 0.1,
            "forecast": 3.0,
            "surprise": i * 0.1,
            "regime_at_episode": "inflation",
        })
    return out


def test_episode_id_is_deterministic_for_idempotency():
    """Same release_id → same episode UUID, every run."""
    from scripts.backfill_macro_episodes import _episode_id_for_release

    rid = "550e8400-e29b-41d4-a716-446655440000"
    e1 = _episode_id_for_release(rid)
    e2 = _episode_id_for_release(rid)
    assert e1 == e2, "episode_id must be deterministic for idempotency"
    # Different release_id → different episode UUID
    e3 = _episode_id_for_release("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    assert e1 != e3


def test_episode_text_includes_release_fields():
    """Episode text must mention indicator_id, release_date, actual, and regime."""
    from scripts.backfill_macro_episodes import _episode_text

    r = {
        "release_date": "2022-03-10",
        "indicator_id": "CPIAUCSL",
        "actual": 7.9,
        "surprise": 0.3,
        "regime_at_episode": "inflation",
    }
    text = _episode_text(r)
    assert "2022-03-10" in text
    assert "CPIAUCSL" in text
    assert "7.9" in text
    assert "inflation" in text
    assert "+0.3" in text or "0.30" in text or "+0.30" in text  # signed surprise


def test_episode_text_handles_missing_surprise_gracefully():
    """Missing surprise key shouldn't blow up — should default to 0."""
    from scripts.backfill_macro_episodes import _episode_text

    r = {
        "release_date": "2022-03-10",
        "indicator_id": "CPIAUCSL",
        "actual": 7.9,
        # no surprise key
        "regime_at_episode": "inflation",
    }
    text = _episode_text(r)
    assert "2022-03-10" in text
    assert "CPIAUCSL" in text


def test_backfill_command_idempotent_in_qdrant(qdrant_test_client):
    """Run the upsert path twice — second run upserts same IDs → zero net new."""
    from qdrant_client.http import models as qm
    from scripts.backfill_macro_episodes import (
        _episode_id_for_release, _episode_text,
    )
    from VM107.core.memory.qdrant_macro_episode_collection import COLLECTION_NAME

    info_before = qdrant_test_client.get_collection(COLLECTION_NAME)
    before = info_before.points_count or 0

    releases = _fake_releases(10)
    points = [
        qm.PointStruct(
            id=str(_episode_id_for_release(r["release_id"])),
            vector=[0.1] * 768,
            payload={
                "episode_id": str(_episode_id_for_release(r["release_id"])),
                "indicator_id": r["indicator_id"],
                "regime_at_episode": r["regime_at_episode"],
                "release_date": r["release_date"],
                "surprise": r["surprise"],
                "decay_weight": 0.9,
                "episode_text": _episode_text(r),
                "created_at": datetime.now(tz=timezone.utc).isoformat(),
            },
        ) for r in releases
    ]
    qdrant_test_client.upsert(collection_name=COLLECTION_NAME, points=points)
    info_after_1 = qdrant_test_client.get_collection(COLLECTION_NAME)
    after_1 = info_after_1.points_count or 0
    assert after_1 == before + 10

    # Second run — same IDs → no net new points
    qdrant_test_client.upsert(collection_name=COLLECTION_NAME, points=points)
    info_after_2 = qdrant_test_client.get_collection(COLLECTION_NAME)
    assert (info_after_2.points_count or 0) == after_1


def test_backfill_decay_weight_formula():
    """exp(-days_old / 180) per RESEARCH §Wave 4 — verify the helper exposes it."""
    from scripts.backfill_macro_episodes import _decay_weight

    # 0 days old → weight = 1.0 exactly
    assert abs(_decay_weight(0) - 1.0) < 1e-9
    # 180 days old → weight = exp(-1) ≈ 0.3679
    assert abs(_decay_weight(180) - 0.36787944117) < 1e-6
    # 360 days old → weight = exp(-2) ≈ 0.1353
    assert abs(_decay_weight(360) - 0.13533528324) < 1e-6
    # Always positive, never negative
    assert _decay_weight(10_000) > 0


def test_backfill_skips_releases_without_regime():
    """Cold-start protection — releases with missing regime_at_episode are
    filtered out before embedding. Tests the filter helper directly."""
    from scripts.backfill_macro_episodes import _filter_eligible_releases

    releases = [
        {"release_id": "a", "regime_at_episode": "inflation"},
        {"release_id": "b", "regime_at_episode": None},
        {"release_id": "c"},  # missing key
        {"release_id": "d", "regime_at_episode": ""},
        {"release_id": "e", "regime_at_episode": "recession"},
    ]
    eligible = _filter_eligible_releases(releases)
    ids = [r["release_id"] for r in eligible]
    assert ids == ["a", "e"]
