"""Phase 169-01 (D-08 / agent-catalogue/13 §2a) — claim_id determinism tests.

Proves the `compute_claim_id` content hash guarantees the future evidence graph +
v7.0-164 ledger depend on:

1. **Idempotency** — the SAME inputs for a fixed `(state_version, knowledge_time)` pair
   always reproduce the SAME id (the compute-at-write-time and PIT-replay cases).
2. **Horizon-distinctness** — a horizon-bearing subject/predicate difference yields a
   DISTINCT id (horizon rides inside subject/predicate, D-08).
3. **`clm_` prefix** — the id is the documented `"clm_" + sha256_hex` shape.
4. **knowledge_time in the hash** — a different `knowledge_time` yields a different id
   (13 §2a includes knowledge_time), while a tz-naive/tz-aware pair for the SAME instant
   normalises to the same id (cross-process reproducibility).

Host-clean: imports the shared `fingpt_core` contract (stdlib + pydantic) only — the same
import path VM107 uses at runtime (editable install of the canonical Dagster copy).
"""

from __future__ import annotations

from datetime import datetime, timezone

from fingpt_core.contracts.assessment import ClaimClass, compute_claim_id

_KT = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
_STATE_VERSION = "v128"


def _base_id(**overrides) -> str:
    """A fixed OBSERVATION claim id, with optional field overrides."""
    kwargs = dict(
        domain="inflation",
        geography="US",
        claim_class=ClaimClass.OBSERVATION,
        subject="core cpi",
        predicate="is",
        object="elevated",
        state_version=_STATE_VERSION,
        knowledge_time=_KT,
    )
    kwargs.update(overrides)
    return compute_claim_id(**kwargs)


def test_claim_id_is_idempotent_for_fixed_state_and_knowledge_time():
    """Same inputs (fixed state_version + knowledge_time) → identical ids."""
    assert _base_id() == _base_id()


def test_claim_id_has_clm_prefix():
    """The id is the documented 'clm_' + sha256 hex shape."""
    cid = _base_id()
    assert cid.startswith("clm_")
    # 'clm_' (4) + 64 hex chars
    assert len(cid) == 4 + 64
    assert all(c in "0123456789abcdef" for c in cid[4:])


def test_claim_id_distinct_across_horizon_bearing_subject_predicate():
    """A horizon-bearing subject/predicate difference → a DISTINCT id (D-08)."""
    nowcast = _base_id(subject="core cpi", predicate="is")
    forecast = _base_id(
        claim_class=ClaimClass.FORECAST,
        subject="core cpi 12m",
        predicate="will be",
        object="moderating",
    )
    assert nowcast != forecast


def test_claim_id_changes_with_knowledge_time():
    """knowledge_time is part of the hash inputs (13 §2a) — a later instant → new id."""
    later = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
    assert _base_id(knowledge_time=_KT) != _base_id(knowledge_time=later)


def test_claim_id_normalises_naive_and_aware_same_instant():
    """A tz-naive datetime (assumed UTC) and its tz-aware twin → the SAME id."""
    naive = datetime(2026, 8, 28, 12, 0)  # no tzinfo → assumed UTC
    assert _base_id(knowledge_time=naive) == _base_id(knowledge_time=_KT)


def test_claim_id_distinct_across_state_version():
    """A different state_version → a distinct id (idempotency is per-fixed-tuple)."""
    assert _base_id(state_version="v128") != _base_id(state_version="v129")


def test_claim_id_accepts_string_claim_class():
    """claim_class may be passed as the enum or its str value — same id either way."""
    assert _base_id(claim_class=ClaimClass.OBSERVATION) == _base_id(claim_class="OBSERVATION")
