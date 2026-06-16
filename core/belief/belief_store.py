"""Brain B9 BeliefStore service.

Phase 87 Wave 5 — Task 2. Per project lock: env-driven, no defaults; LLM-direct
propose blocked at API level via the authorize_proposer gate.

Construction fails-fast when BELIEF_STORE_POSTGRES_URL or BELIEF_STORE_MONGO_URL
is missing — the asset materialisation on Sunday 02:00 UTC must not silently
silently no-op against an unconfigured environment.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import psycopg2
import pymongo

from .bayesian import BeliefSnapshot, apply_weekly_decay, bayesian_update
from .phase53_lifecycle import retire_belief
from .proposal_authorization import authorize_proposer


MONGO_CACHE_TTL_S = 60  # per Open Q 2 — 60-second TTL on belief query cache


class BeliefStore:
    """Brain B9 belief read/write service.

    Read path: Mongo `belief_query_cache` (TTL 60s) → Postgres `belief` table.
    Write path: authorize_proposer → Bayesian update → WORM insert → cache invalidate.
    """

    def __init__(
        self,
        postgres_url: str | None = None,
        mongo_url: str | None = None,
    ):
        pg_url = postgres_url or os.environ.get("BELIEF_STORE_POSTGRES_URL")
        if not pg_url:
            raise RuntimeError(
                "BELIEF_STORE_POSTGRES_URL required — env-driven, no default"
            )
        mongo = mongo_url or os.environ.get("BELIEF_STORE_MONGO_URL")
        if not mongo:
            raise RuntimeError(
                "BELIEF_STORE_MONGO_URL required — env-driven, no default"
            )
        self._pg = psycopg2.connect(pg_url)
        self._mongo = pymongo.MongoClient(mongo).get_default_database()
        self._cache = self._mongo.get_collection("belief_query_cache")
        # TTL index — recreate idempotently
        self._cache.create_index(
            "expires_at", expireAfterSeconds=0, background=True,
        )

    # ── Reads ────────────────────────────────────────────────────────────
    def query(self, *, subject_type: str, subject_id: str) -> dict | None:
        key = f"{subject_type}:{subject_id}"
        cached = self._cache.find_one({"_id": key})
        if cached and cached["expires_at"] > datetime.now(tz=timezone.utc):
            return cached["belief"]
        with self._pg.cursor() as cur:
            cur.execute(
                """
                SELECT belief_id, probability, confidence, evidence_count,
                       contradicting_count, lifecycle_state, is_active
                FROM belief
                WHERE subject_type = %s AND subject_id = %s AND is_active = TRUE
                ORDER BY created_at DESC LIMIT 1
                """,
                (subject_type, subject_id),
            )
            row = cur.fetchone()
        if not row:
            return None
        belief = {
            "belief_id": str(row[0]),
            "probability": row[1],
            "confidence": row[2],
            "evidence_count": row[3],
            "contradicting_count": row[4],
            "lifecycle_state": row[5],
            "is_active": row[6],
        }
        self._cache.replace_one(
            {"_id": key},
            {
                "_id": key,
                "belief": belief,
                "expires_at": datetime.now(tz=timezone.utc)
                + timedelta(seconds=MONGO_CACHE_TTL_S),
            },
            upsert=True,
        )
        return belief

    # ── Writes ───────────────────────────────────────────────────────────
    def propose(
        self,
        *,
        proposer_id: str,
        subject_type: str,
        subject_id: str,
        confirms_belief: bool,
        evidence: dict,
    ) -> str:
        """Propose a Bayesian update. Raises PermissionError for LLM/unknown proposers."""
        authorize_proposer(proposer_id)  # raises PermissionError for LLM/unknown
        existing = self.query(subject_type=subject_type, subject_id=subject_id)
        prior = BeliefSnapshot(
            probability=(existing or {}).get("probability", 0.5),
            confidence=(existing or {}).get("confidence", 0.5),
            evidence_count=(existing or {}).get("evidence_count", 0),
            contradicting_count=(existing or {}).get("contradicting_count", 0),
        )
        post = bayesian_update(prior=prior, confirms_belief=confirms_belief)
        new_belief_id = uuid.uuid4()
        with self._pg.cursor() as cur:
            cur.execute(
                """
                INSERT INTO belief (belief_id, subject_type, subject_id, statement,
                    probability, confidence, evidence_count, contradicting_count,
                    source_domains, created_at, last_confirmed_at, decay_model,
                    decay_rate, is_active, lifecycle_state, supersedes_belief_id,
                    citations
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    str(new_belief_id),
                    subject_type,
                    subject_id,
                    f"current {subject_type} is {subject_id}",
                    post.probability,
                    post.confidence,
                    post.evidence_count,
                    post.contradicting_count,
                    [proposer_id],
                    datetime.now(tz=timezone.utc),
                    datetime.now(tz=timezone.utc),
                    "bayesian",
                    0.7071,  # LOCK-5 weekly decay factor
                    True,
                    "shadow",
                    (existing or {}).get("belief_id"),
                    [evidence],
                ),
            )
        self._pg.commit()
        self._cache.delete_one({"_id": f"{subject_type}:{subject_id}"})
        return str(new_belief_id)

    def audit(self, belief_id: str) -> list[dict]:
        """Walk supersedes_belief_id chain (WORM lineage)."""
        chain: list[dict] = []
        current = belief_id
        with self._pg.cursor() as cur:
            while current:
                cur.execute(
                    "SELECT belief_id, supersedes_belief_id, probability, confidence,"
                    " lifecycle_state, created_at, citations "
                    "FROM belief WHERE belief_id = %s",
                    (current,),
                )
                row = cur.fetchone()
                if not row:
                    break
                chain.append(
                    {
                        "belief_id": str(row[0]),
                        "supersedes": str(row[1]) if row[1] else None,
                        "probability": row[2],
                        "confidence": row[3],
                        "lifecycle_state": row[4],
                        "created_at": row[5].isoformat(),
                        "citations": row[6],
                    }
                )
                current = row[1]
        return chain

    def retire(self, belief_id: str, reason: str, approver_id: str) -> None:
        belief = {"belief_id": belief_id, "lifecycle_state": "active"}
        action = retire_belief(belief, reason=reason, approver_id=approver_id)
        with self._pg.cursor() as cur:
            cur.execute(
                "UPDATE belief SET is_active = FALSE, lifecycle_state = 'retired', "
                "supersedes_belief_id = %s WHERE belief_id = %s",
                (belief_id, belief_id),
            )
            cur.execute(
                "INSERT INTO governance_action (belief_id, from_state, to_state, "
                "approver_id, reason) VALUES (%s,%s,%s,%s,%s)",
                (
                    belief_id,
                    action.from_state,
                    action.to_state,
                    action.approver_id,
                    action.reason,
                ),
            )
        self._pg.commit()

    # ── Dagster asset hook (Task 3) ──────────────────────────────────────
    def apply_weekly_decay_to_all_active(self) -> dict:
        """Called by Dagster `belief_weekly_decay` asset (Task 3).

        Iterates all is_active=TRUE beliefs, applies LOCK-5 14-day half-life decay,
        retires any whose confidence drops below 0.15. Returns stats dict.
        """
        stats = {"decayed": 0, "retired": 0}
        with self._pg.cursor() as cur:
            cur.execute(
                "SELECT belief_id, probability, confidence, evidence_count, "
                "contradicting_count FROM belief WHERE is_active = TRUE"
            )
            rows = cur.fetchall()
            for bid, prob, conf, ec, cc in rows:
                prior = BeliefSnapshot(
                    probability=prob,
                    confidence=conf,
                    evidence_count=ec,
                    contradicting_count=cc,
                )
                decayed, should_retire = apply_weekly_decay(prior)
                if should_retire:
                    self.retire(
                        str(bid),
                        reason="decay_floor",
                        approver_id="system_decay",
                    )
                    stats["retired"] += 1
                else:
                    cur.execute(
                        "UPDATE belief SET probability=%s, confidence=%s, "
                        "evidence_count=%s, contradicting_count=%s "
                        "WHERE belief_id=%s",
                        (
                            decayed.probability,
                            decayed.confidence,
                            decayed.evidence_count,
                            decayed.contradicting_count,
                            str(bid),
                        ),
                    )
                    stats["decayed"] += 1
        self._pg.commit()
        return stats
