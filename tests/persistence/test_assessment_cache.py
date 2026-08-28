"""Phase 169-04 (D-09 / G4 / AGV-11) — AssessmentCache cache_key + TTL-precedence tests.

Proves the two correctness rules the compute-at-write-time / read-many store MUST hold so a
stale assessment can never be served when a non-state input changed:

1. **Full-manifest fingerprint** — `compute_cache_key` hashes the exact D-09 tuple
   (agent_version, domain_definition_version, state_version, knowledge_version,
   feature_set_version, prompt_version, model, knowledge_time). Identical inputs → identical
   key; ANY single input change → a different key.
2. **TTL precedence** — `valid = cache_key_match AND now < valid_until`. A hash-mismatch
   invalidates even before expiry; a TTL-expiry invalidates even on a hash-match.

Hermetic: a trivial in-memory backend (get/put) + an injected clock stand in for the live
MongoCachedCollection so no Mongo/Redis is required. The production wiring reuses the landed
`MongoCachedCollection` (get + put) — see assessment_cache.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fingpt_core.contracts.assessment import (
    Confidence,
    DomainAssessment,
    Horizon,
    ReproducibilityManifest,
)

from core.persistence.assessment_cache import (
    AssessmentCache,
    compute_cache_key,
    is_valid,
)

_KT = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)


def _key(**overrides) -> str:
    kwargs = dict(
        agent_version="1.0.0",
        domain_definition_version="dd-1.0.0",
        state_version="v128",
        knowledge_version="kb-2026.08",
        feature_set_version="fs-1",
        prompt_version="p-1",
        model="deterministic",
        knowledge_time=_KT,
    )
    kwargs.update(overrides)
    return compute_cache_key(**kwargs)


# ---------------------------------------------------------------------------
# compute_cache_key — full-manifest fingerprint
# ---------------------------------------------------------------------------


def test_cache_key_is_idempotent_for_identical_inputs():
    assert _key() == _key()


def test_cache_key_has_ac_prefix_and_sha256_shape():
    k = _key()
    assert k.startswith("ac_")
    assert len(k) == 3 + 64
    assert all(c in "0123456789abcdef" for c in k[3:])


def test_cache_key_normalises_naive_and_aware_same_instant():
    """A tz-naive knowledge_time (assumed UTC) hashes identically to its tz-aware twin."""
    naive = datetime(2026, 8, 28, 12, 0)
    assert _key(knowledge_time=naive) == _key(knowledge_time=_KT)


def test_cache_key_changes_on_every_manifest_input():
    """Changing ANY single manifest input yields a different key (no collisions)."""
    base = _key()
    variants = {
        "agent_version": "1.0.1",
        "domain_definition_version": "dd-1.0.1",
        "state_version": "v129",
        "knowledge_version": "kb-2026.09",
        "feature_set_version": "fs-2",
        "prompt_version": "p-2",
        "model": "gpt-x",
        "knowledge_time": _KT + timedelta(hours=1),
    }
    seen = {base}
    for field, value in variants.items():
        k = _key(**{field: value})
        assert k != base, f"changing {field} did not change the cache_key"
        assert k not in seen, f"{field} collided with a prior key"
        seen.add(k)


# ---------------------------------------------------------------------------
# is_valid — TTL precedence (both invalidation rules)
# ---------------------------------------------------------------------------


def test_is_valid_true_on_hash_match_before_expiry():
    now = _KT
    assert is_valid("ac_abc", "ac_abc", now, valid_until=now + timedelta(seconds=60)) is True


def test_is_valid_false_on_hash_mismatch_even_when_not_expired():
    """Rule (b): cache_key_mismatch + not-expired → invalid."""
    now = _KT
    assert is_valid("ac_stored", "ac_request", now, valid_until=now + timedelta(seconds=60)) is False


def test_is_valid_false_on_expiry_even_on_hash_match():
    """Rule (a): cache_key_match + expired → invalid."""
    now = _KT
    assert is_valid("ac_abc", "ac_abc", now, valid_until=now - timedelta(seconds=1)) is False


def test_is_valid_false_at_exact_expiry_boundary():
    """`now < valid_until` is strict — equality is already expired."""
    now = _KT
    assert is_valid("ac_abc", "ac_abc", now, valid_until=now) is False


# ---------------------------------------------------------------------------
# AssessmentCache round-trip + precedence over an injected backend + clock
# ---------------------------------------------------------------------------


class _InMemoryBackend:
    """Minimal get/put backend (the surface AssessmentCache uses from MongoCachedCollection).

    Duck-types the two methods AssessmentCache calls so tests need no live Mongo/Redis. The
    real wiring passes a MongoCachedCollection (which exposes the same get/put + Redis-down
    degradation).
    """

    def __init__(self):
        self._store: dict[str, dict] = {}

    def get(self, doc_id: str):
        return self._store.get(doc_id)

    def put(self, doc_id: str, document: dict):
        self._store[doc_id] = dict(document)
        return document


def _assessment() -> DomainAssessment:
    return DomainAssessment(
        domain="inflation",
        geography_id="US",
        geography_type="country",
        state_version="v128",
        horizon=Horizon.NOWCAST,
        level=0.4,
        momentum=-0.1,
        surprise=1.2,
        confidence=Confidence(data=0.9, state_model=0.8, interpretation=0.7, forecast=0.6, overall=0.75),
        manifest=ReproducibilityManifest(
            agent_version="1.0.0",
            model="deterministic",
            prompt_version="p-1",
            state_version="v128",
            feature_set_version="fs-1",
            knowledge_version="kb-2026.08",
            knowledge_time=_KT,
            execution_time=_KT,
        ),
        knowledge_time=_KT,
    )


def test_cache_round_trips_domain_assessment():
    """put then get with a matching key inside TTL returns an equal DomainAssessment."""
    clock = {"now": _KT}
    cache = AssessmentCache(_InMemoryBackend(), now_fn=lambda: clock["now"])
    key = _key()
    cache.put("doc-1", _assessment(), cache_key=key, valid_until=_KT + timedelta(seconds=60))

    got = cache.get("doc-1", request_key=key)
    assert isinstance(got, DomainAssessment)
    assert got == _assessment()


def test_cache_get_miss_returns_none_on_hash_mismatch():
    """A different manifest fingerprint invalidates even though TTL has not expired."""
    cache = AssessmentCache(_InMemoryBackend(), now_fn=lambda: _KT)
    cache.put("doc-1", _assessment(), cache_key=_key(), valid_until=_KT + timedelta(seconds=60))

    stale = cache.get("doc-1", request_key=_key(model="gpt-x"))
    assert stale is None


def test_cache_get_miss_returns_none_on_ttl_expiry():
    """A matching fingerprint past valid_until invalidates (TTL-expiry)."""
    clock = {"now": _KT}
    cache = AssessmentCache(_InMemoryBackend(), now_fn=lambda: clock["now"])
    key = _key()
    cache.put("doc-1", _assessment(), cache_key=key, valid_until=_KT + timedelta(seconds=30))

    clock["now"] = _KT + timedelta(seconds=31)
    assert cache.get("doc-1", request_key=key) is None


def test_cache_get_absent_returns_none():
    cache = AssessmentCache(_InMemoryBackend(), now_fn=lambda: _KT)
    assert cache.get("missing", request_key=_key()) is None
