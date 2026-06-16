"""Phase 87 Wave 4a — backfill the ``macro_episode`` Qdrant collection.

Pulls release history from the VM101 typed economic_event API (NOT parquet
or cold-data — per Phase 47.2 cross-VM-filesystem lock), embeds each release
via the Phase 58 EmbeddingService singleton (all-mpnet-base-v2, 768-dim,
shared with the trade_episode collection), and upserts a deterministic
``macro_episode`` point per release. Idempotent — second run with the same
release_id set produces zero net new points (episode_id = uuid5(release_id)).

Usage::

    python -m scripts.backfill_macro_episodes --years-back 5
    python -m scripts.backfill_macro_episodes --dry-run
    python -m scripts.backfill_macro_episodes --batch-size 500

Env vars required (fail-fast — no ``os.getenv("X", "default")`` patterns):
    QDRANT_URL              — e.g., http://192.168.1.105:6333
    VM101_INTERNAL_BASE_URL — e.g., http://192.168.1.201:8001

Per Phase 47.6 capability-registry lock the backfill is documented in the
service YAML; the runtime is in-process Python.

VM107 is not a Django project; this ships as a ``python -m scripts.*``
CLI mirroring ``scripts/load_macro_graph_seed.py``. The plan-of-record
described it as a Django management command — that wording was aspirational
(VM107 has no Django settings.py); a Rule 3 Blocking deviation adapted it
to the actual VM107 layout.

Exit codes:
    0 — backfill succeeded (or dry-run completed)
    1 — env var missing, VM101 API error, or runtime error
"""
from __future__ import annotations

import argparse
import logging
import math
import os
import pathlib
import sys
import uuid
from datetime import datetime, timezone
from typing import Iterable

# Ensure VM107 root + FinGPT parent are on sys.path so VM107.* imports resolve
_VM107_ROOT = pathlib.Path(__file__).resolve().parent.parent
_FINGPT_ROOT = _VM107_ROOT.parent
for _p in (str(_VM107_ROOT), str(_FINGPT_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

logger = logging.getLogger("backfill_macro_episodes")


# ─── Helpers (extracted as module-level for unit testability) ──────────────
def _env_required(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        sys.stderr.write(
            f"ERROR: env var {key} required for backfill_macro_episodes "
            "(no default fallback — CLAUDE.md no-fallback-defaults lock)\n"
        )
        sys.exit(1)
    return val


def _episode_id_for_release(release_id: str) -> uuid.UUID:
    """Deterministic episode UUID derived from the release_id namespace.

    Second backfill of the same release upserts the same point — Qdrant
    treats it as a no-op when payload + vector are unchanged.
    """
    return uuid.uuid5(uuid.NAMESPACE_DNS, f"macro_episode:{release_id}")


def _episode_text(release: dict) -> str:
    """Compose the embeddable text for one macro release.

    Format (Phase 87 RESEARCH §Wave 4 reference shape)::

        On <release_date> <indicator_id> printed <actual> (surprise +/-N.NN).
        Regime: <regime_at_episode>.
    """
    surprise = release.get("surprise", 0) or 0
    return (
        f"On {release['release_date']} {release['indicator_id']} printed "
        f"{release['actual']} (surprise {surprise:+.2f}). "
        f"Regime: {release.get('regime_at_episode', 'unknown')}."
    )


def _decay_weight(days_old: int) -> float:
    """Temporal decay: ``exp(-days_old / 180)`` per RESEARCH §Wave 4.

    180-day half-life-ish curve (technically e-fold at 180 days): a 6-month-
    old episode carries ~37% weight; a 1-year-old carries ~13%; a 2-year-old
    carries ~1.8%. Combined multiplicatively with cosine similarity at query
    time so recency biases ranking without filtering out distant-but-similar
    episodes outright.
    """
    return math.exp(-max(0, days_old) / 180.0)


def _filter_eligible_releases(releases: Iterable[dict]) -> list[dict]:
    """Drop releases lacking ``regime_at_episode`` (cold-start protection —
    we cannot label an episode's prior regime if we don't know what it was).
    """
    return [r for r in releases if r.get("regime_at_episode")]


def _days_old_from_release_date(release_date: str) -> int:
    """Robust ISO-date → days-old converter. Tolerates timezone-naive and
    timezone-aware ISO strings; returns 0 for un-parseable input."""
    try:
        dt = datetime.fromisoformat(release_date)
    except (TypeError, ValueError):
        return 0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(tz=timezone.utc) - dt).days)


# ─── Main backfill flow ────────────────────────────────────────────────────
def _fetch_releases(vm101_url: str, years_back: int) -> list[dict]:
    """HTTPX GET against VM101 typed economic_event API.

    Per Phase 47.2 lock VM107 NEVER touches /cold-data or /mnt/parquet
    directly; the typed API is the only sanctioned channel.
    """
    import httpx

    with httpx.Client(timeout=30) as http:
        resp = http.get(
            f"{vm101_url.rstrip('/')}/api/v2/economic-event/list",
            params={"years": years_back},
        )
        resp.raise_for_status()
        payload = resp.json()
    return payload.get("releases", [])


def _build_point(release: dict, vec: list[float]) -> dict:
    """Construct one Qdrant PointStruct as a plain dict (let the caller
    convert to the qdrant_client model so this helper stays dep-free for
    unit tests)."""
    ep_id = _episode_id_for_release(str(release["release_id"]))
    text = _episode_text(release)
    days_old = _days_old_from_release_date(release["release_date"])
    decay = _decay_weight(days_old)
    return {
        "id": str(ep_id),
        "vector": list(vec),
        "payload": {
            "episode_id": str(ep_id),
            "indicator_id": release["indicator_id"],
            "regime_at_episode": release["regime_at_episode"],
            "release_date": release["release_date"],
            "surprise": release.get("surprise", 0),
            "decay_weight": decay,
            "episode_text": text,
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="backfill_macro_episodes",
        description="Phase 87 Wave 4a — populate macro_episode Qdrant collection",
    )
    parser.add_argument("--years-back", type=int, default=5)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument(
        "--verbose", action="store_true", help="enable INFO logging"
    )
    opts = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if opts.verbose else logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    qdrant_url = _env_required("QDRANT_URL")
    vm101_url = _env_required("VM101_INTERNAL_BASE_URL")

    # Lazy imports — keep test surface small and avoid forcing the
    # embedding model load at import time.
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qm
    from VM107.core.memory.qdrant_macro_episode_collection import (
        COLLECTION_NAME, ensure_macro_episode_collection,
    )

    client = QdrantClient(url=qdrant_url, check_compatibility=False)
    ensure_macro_episode_collection(client)

    # Phase 58 EmbeddingService singleton. Lives in fingpt_core (not VM107)
    # per the Mac dev / Docker prod split — see plugins/_memory/backend/
    # redis_cache.py for the canonical comment on the import boundary.
    from fingpt_core.embedding import EmbeddingService  # noqa: E402
    embedder = EmbeddingService()

    releases = _fetch_releases(vm101_url, opts.years_back)
    sys.stdout.write(
        f"Pulled {len(releases)} releases from VM101 typed API\n"
    )

    eligible = _filter_eligible_releases(releases)
    sys.stdout.write(
        f"Eligible (have regime_at_episode): {len(eligible)} of {len(releases)}\n"
    )

    batch: list = []
    upserts = 0
    for r in eligible:
        text = _episode_text(r)
        # EmbeddingService.embed is async in some configurations and sync
        # in others; the call-path that ships in production accepts a single
        # text and returns a list[float].
        embed_out = embedder.embed(text)
        vec = (
            embed_out
            if isinstance(embed_out, list)
            else embed_out.embeddings[0]
        )
        point_dict = _build_point(r, vec)
        batch.append(qm.PointStruct(
            id=point_dict["id"],
            vector=point_dict["vector"],
            payload=point_dict["payload"],
        ))
        if len(batch) >= opts.batch_size:
            if not opts.dry_run:
                client.upsert(collection_name=COLLECTION_NAME, points=batch)
            upserts += len(batch)
            batch = []

    if batch:
        if not opts.dry_run:
            client.upsert(collection_name=COLLECTION_NAME, points=batch)
        upserts += len(batch)

    label = "[dry-run] would upsert" if opts.dry_run else "Upserted"
    sys.stdout.write(f"{label} {upserts} episodes\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
