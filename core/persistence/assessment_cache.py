"""Phase 169-04 (D-09 / G4+G5 / AGV-11) — AssessmentCache + work_key single-flight.

The compute-at-write-time / read-many plumbing a Domain Agent's `DomainAssessment`
(fingpt_core.contracts.assessment) needs so that:

- **G4 (AssessmentCache).** A cached assessment is served ONLY when the *full manifest
  fingerprint* still matches AND the entry is inside its TTL. `compute_cache_key` hashes
  the exact D-09 tuple (agent_version, domain_definition_version, state_version,
  knowledge_version, feature_set_version, prompt_version, model, knowledge_time); the
  read rule `valid = cache_key_match AND now < valid_until` (`is_valid`) makes a
  hash-mismatch OR a TTL-expiry both invalidate. This makes stale-serve impossible when
  any non-state input changes.
- **G5 (work_key single-flight).** `compute_work_key` fingerprints the output-shape +
  knowledge_time so replay-vs-live and different detail_level/horizon get distinct keys;
  `acquire_single_flight` uses Redis `SET key val NX EX ttl` to dedup concurrent compute
  across processes, degrading to *proceed-without-lock* (never raising) when Redis is down.

Reuse, not reinvention: `AssessmentCache` wraps the landed `MongoCachedCollection`
(core/persistence/mongo_cache.py) for its TTL `setex` + Mongo authority + graceful
Redis-down degradation — it only adds the manifest-fingerprint key and the TTL-precedence
read rule on top. Hashing is stdlib `hashlib.sha256` over a canonicalized serialization
(stable key order, ISO-8601 UTC knowledge_time) so keys are reproducible across the async
fan-out (T-169-04-03).

Dependency note: this is a VM107-side store — it imports the shared `fingpt_core`
`DomainAssessment` contract; `fingpt_core` never imports a VM107 type (D-03).
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional, Protocol

from fingpt_core.contracts.assessment import DomainAssessment

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Canonical serialization helpers (cross-process reproducibility, T-169-04-03)
# ---------------------------------------------------------------------------


def _canonical_knowledge_time(knowledge_time: datetime | str) -> str:
    """Normalise `knowledge_time` to a canonical ISO-8601 UTC string.

    A tz-naive datetime is assumed UTC (the lake/pack convention); a tz-aware datetime is
    converted to UTC. This keeps the hash stable across processes that carry the same
    instant with different tzinfo — mirrors `assessment.compute_claim_id` exactly (D-08/D-09).
    """
    if isinstance(knowledge_time, datetime):
        kt = knowledge_time
        if kt.tzinfo is None:
            kt = kt.replace(tzinfo=timezone.utc)
        return kt.astimezone(timezone.utc).isoformat()
    return str(knowledge_time)


def _sha256(payload: dict[str, Any], *, prefix: str) -> str:
    """`prefix + sha256_hex(canonical_json(payload))` with a stable key order."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return prefix + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# G4 — cache_key (full-manifest fingerprint) + TTL precedence
# ---------------------------------------------------------------------------


def compute_cache_key(
    agent_version: str,
    domain_definition_version: str,
    state_version: str,
    knowledge_version: str,
    feature_set_version: str,
    prompt_version: str,
    model: str,
    knowledge_time: datetime | str,
) -> str:
    """Return the deterministic AssessmentCache key over the exact D-09 manifest tuple.

    `cache_key = "ac_" + sha256_hex(canonical(agent_version, domain_definition_version,
    state_version, knowledge_version, feature_set_version, prompt_version, model,
    knowledge_time))`. Changing ANY input changes the key, so a cached assessment is
    invalidated the moment any non-state input (agent code, prompt, model, feature set,
    knowledge cut) changes — the anti-stale-serve guarantee (AGV-11, T-169-04-01).
    """
    payload = {
        "agent_version": agent_version,
        "domain_definition_version": domain_definition_version,
        "state_version": state_version,
        "knowledge_version": knowledge_version,
        "feature_set_version": feature_set_version,
        "prompt_version": prompt_version,
        "model": model,
        "knowledge_time": _canonical_knowledge_time(knowledge_time),
    }
    return _sha256(payload, prefix="ac_")


def is_valid(
    stored_key: str,
    request_key: str,
    now: datetime,
    valid_until: datetime,
) -> bool:
    """The TTL-precedence read rule: `valid = cache_key_match AND now < valid_until`.

    Both invalidation rules fall out of this single expression:
    - hash-mismatch (`stored_key != request_key`) → invalid, EVEN IF not expired;
    - TTL-expiry (`now >= valid_until`) → invalid, EVEN ON a hash-match.

    `now < valid_until` is strict, so the exact expiry instant is already invalid.
    """
    return stored_key == request_key and now < valid_until


class _GetPutBackend(Protocol):
    """The narrow surface AssessmentCache uses — satisfied by MongoCachedCollection."""

    def get(self, doc_id: str) -> Optional[dict]:  # pragma: no cover - typing only
        ...

    def put(self, doc_id: str, document: dict) -> Any:  # pragma: no cover - typing only
        ...


class AssessmentCache:
    """Compute-at-write-time / read-many store for `DomainAssessment` (G4).

    Wraps a `MongoCachedCollection`-compatible backend (Mongo authority + Redis hot cache +
    `setex` TTL + graceful Redis-down degradation) and layers the full-manifest `cache_key`
    plus the `is_valid` TTL-precedence read rule on top. A read returns the cached
    assessment ONLY when the stored fingerprint matches the caller's `request_key` AND the
    entry is inside its `valid_until`; otherwise it returns `None` (a miss → recompute),
    never a stale assessment.

    The backend's own get/put already degrade to a durable read when Redis is down, so this
    class never has to special-case Redis availability (T-169-04-02).
    """

    def __init__(
        self,
        backend: _GetPutBackend,
        *,
        now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self.backend = backend
        self._now_fn = now_fn

    def put(
        self,
        doc_id: str,
        assessment: DomainAssessment,
        *,
        cache_key: str,
        valid_until: datetime,
    ) -> None:
        """Persist an assessment tagged with its manifest `cache_key` and `valid_until`.

        The record is a plain dict (JSON-safe via pydantic `model_dump(mode="json")`) so it
        round-trips through the backend's `setex`/Mongo write unchanged.
        """
        record = {
            "_id": doc_id,
            "cache_key": cache_key,
            "valid_until": _canonical_knowledge_time(valid_until),
            "assessment": assessment.model_dump(mode="json"),
        }
        self.backend.put(doc_id, record)

    def get(
        self,
        doc_id: str,
        *,
        request_key: str,
        now: Optional[datetime] = None,
    ) -> Optional[DomainAssessment]:
        """Return the cached `DomainAssessment` iff fingerprint-match AND not-expired.

        Returns `None` on absence, hash-mismatch, or TTL-expiry (all treated as a cache
        miss → recompute). Never serves a stale assessment.
        """
        record = self.backend.get(doc_id)
        if not record:
            return None

        stored_key = record.get("cache_key", "")
        valid_until = self._parse_dt(record.get("valid_until"))
        now = now if now is not None else self._now_fn()
        if valid_until is None or not is_valid(stored_key, request_key, now, valid_until):
            return None

        return DomainAssessment.model_validate(record["assessment"])

    @staticmethod
    def _parse_dt(value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            dt = value
        else:
            try:
                dt = datetime.fromisoformat(str(value))
            except ValueError:
                return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
