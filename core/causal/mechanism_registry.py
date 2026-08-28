"""Phase 170 Plan 02 (D-03) — frozen `CausalMechanismRegistry` store + keyed lookup.

The Causality Critic (Constitution rule 11) asks one deterministic question of a
claim: *does a registered transmission mechanism exist for this
`(domain, claim_class, subject -> predicate)` key?* A registered key returns its
`MechanismRecord`; a bare-correlation key with no seeded mechanism returns
`None` — the deterministic REJECT signal (SC#2).

This module is the *store* only — it holds records + a pure lookup and derives a
content-hash `registry_version`. Seeding (the reuse-first read of the 169
`domain_definition:` blocks) lives in `core/causal/seed.py`.

Discipline mirrored from `core/agents/domain_definition.py` (the 169 analog):
- Frozen `extra="forbid"` models (closed contracts).
- Deterministic first-matching-record-wins lookup; a `None`/unknown key
  component NEVER matches (carry `StateRule.matches` L79-88 — an unmeasured
  value cannot satisfy a match).
- No IO, no wall-clock, no LLM SDK import in the store (engine-lock D-02).
"""
from __future__ import annotations

import hashlib
import json
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


def _norm(value: object | None) -> str | None:
    """Normalise a key component for matching.

    An enum is reduced to its `.value`; a string is stripped + casefolded. A
    `None`/blank component returns `None` — and a `None` component can never
    match (carry the `StateRule.matches` "Unknown != match" discipline). Any
    non-string, non-enum value also normalises to `None` (never silently matches).
    """
    if value is None:
        return None
    if isinstance(value, Enum):
        value = value.value
    if not isinstance(value, str):
        return None
    normalised = value.strip().casefold()
    return normalised or None


class MechanismRecord(BaseModel):
    """One registered transmission mechanism (frozen, closed contract).

    The `mechanism` text is a plausible transmission description drawn
    reuse-first from the seed source's `signal_roles` / `invalidation_conditions`
    / `assumptions` — never invented free-form (D-03, engine-lock D-02).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    domain: str = Field(min_length=1)
    claim_class: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    mechanism: str = Field(min_length=1, description="Registered transmission mechanism (reuse-first).")
    version: str = Field(min_length=1, description="Seed-source config version this record derives from.")

    def matches(
        self,
        domain: object | None,
        claim_class: object | None,
        subject: object | None,
        predicate: object | None,
    ) -> bool:
        """True iff ALL four normalised key components equal this record's.

        Any `None`/unknown component fails the match (an unmeasured key
        component can never satisfy a lookup — `Unknown != match`).
        """
        wanted = (_norm(domain), _norm(claim_class), _norm(subject), _norm(predicate))
        if any(component is None for component in wanted):
            return False
        return wanted == (
            _norm(self.domain),
            _norm(self.claim_class),
            _norm(self.subject),
            _norm(self.predicate),
        )


class CausalMechanismRegistry(BaseModel):
    """The frozen per-`(domain, claim_class, subject/predicate)` mechanism store.

    Holds an ordered tuple of `MechanismRecord` and a pure, deterministic
    `lookup`. Seed order is preserved (the seed sorts its glob) so the
    `registry_version` content hash is reproducible.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    records: tuple[MechanismRecord, ...] = ()

    def lookup(
        self,
        domain: object | None,
        claim_class: object | None,
        subject: object | None,
        predicate: object | None,
    ) -> MechanismRecord | None:
        """Return the first `MechanismRecord` matching the key, else `None`.

        Pure — no IO, no LLM, no wall-clock. First-matching-record-wins (seed
        order). A `None`/unknown key component yields `None` (the deterministic
        REJECT signal that drives SC#2 / Constitution 11).
        """
        for record in self.records:
            if record.matches(domain, claim_class, subject, predicate):
                return record
        return None

    @property
    def registry_version(self) -> str:
        """A reproducible content hash over the loaded records.

        Deterministic (stable JSON of the normalised key + mechanism + version
        for every record, in seed order). Downstream verdicts derive their
        `registry_snapshot_hash` from this so a given registry always hashes the
        same regardless of process/wall-clock.
        """
        payload = [
            {
                "domain": record.domain,
                "claim_class": record.claim_class,
                "subject": record.subject,
                "predicate": record.predicate,
                "mechanism": record.mechanism,
                "version": record.version,
            }
            for record in self.records
        ]
        blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


__all__ = [
    "CausalMechanismRegistry",
    "MechanismRecord",
]
