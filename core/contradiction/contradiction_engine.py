"""Phase 89 Wave 3 — B13 ContradictionEngine service.

Provides:
  - detect_divergence: per-asset sigma computation from predicted/actual/sigma_hist
  - grade_severity: delegates to severity_grader (data-driven from contract YAML)
  - active_blocking: Postgres-direct query (Pitfall 2 — no Mongo cache)
  - increment_contradicting_count: calls BeliefStore.propose(confirms_belief=False, ...)
  - write_contradiction: inserts ContradictionArtifact into macro_contradictions table
  - ContradictionArtifact: Pydantic model matching ARCHITECTURE §5.4 SQL schema

Per project locks:
  - CONTRADICTION_POSTGRES_URL read from env — fail-fast, NO default.
  - No hardcoded URLs. No Mongo cache in active_blocking (Pitfall 2).
  - BeliefStore must be injected (testable) or constructed from env.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import psycopg2
from pydantic import BaseModel, ConfigDict, Field

from emitters.source_health_registry import SourceHealthRegistry

from .severity_grader import SeverityResult, grade_severity

logger = logging.getLogger(__name__)


# ── ContradictionArtifact Pydantic model ─────────────────────────────────────

class ContradictionArtifact(BaseModel):
    """B13 contradiction artifact — matches macro_contradictions Postgres schema.

    Per ARCHITECTURE §5.4. All columns represented as typed fields.
    """

    contradiction_id: UUID
    indicator_id: str
    asset_keys: list[str] = Field(default_factory=list)
    predicted_value: dict[str, Any] = Field(default_factory=dict)
    actual_value: dict[str, Any] = Field(default_factory=dict)
    divergence_sigma: dict[str, Any] = Field(default_factory=dict)
    severity: str  # validated in post_init or via validator
    explanation_candidates: list[dict] = Field(default_factory=list)
    related_belief_id: UUID | None = None
    conflict_strength: float
    unresolved: bool = True
    resolution_strategy: str | None = None
    resolution_artifact_id: UUID | None = None
    detected_at: datetime
    resolved_at: datetime | None = None

    model_config = ConfigDict(arbitrary_types_allowed=True)


# ── ContradictionEngine ───────────────────────────────────────────────────────

class ContradictionEngine:
    """B13 contradiction engine — detect, grade, persist, and gate confident emit.

    Constructor reads CONTRADICTION_POSTGRES_URL env var (fail-fast — no default).

    Args:
        belief_store: Optional BeliefStore instance for wiring. If None, engine
                      will create one lazily when increment_contradicting_count is
                      called (requires BELIEF_STORE_POSTGRES_URL + BELIEF_STORE_MONGO_URL).
        contract: Optional pre-loaded B13 contract dict. If None, loaded lazily
                  from registry/contract/contract.b13_contradiction_engine.yaml.
    """

    def __init__(
        self,
        belief_store: Any | None = None,
        contract: dict | None = None,
    ):
        pg_url = os.environ.get("CONTRADICTION_POSTGRES_URL")
        if not pg_url:
            raise RuntimeError(
                "CONTRADICTION_POSTGRES_URL required — env-driven, no default. "
                "Set CONTRADICTION_POSTGRES_URL in your environment before starting."
            )
        self._pg_url = pg_url
        # connect_timeout bounds the eager psycopg2 connect so a down Postgres
        # fast-fails within budget instead of hanging construction (SC-1).
        # Env-driven resilience default, not a target/credential fallback
        # (D-05/D-06). Report guard matches this module's fail-fast idiom (D-07).
        try:
            self._conn = psycopg2.connect(
                pg_url,
                connect_timeout=int(os.getenv("A0_PG_CONNECT_TIMEOUT", "5")),
            )
        except Exception as exc:
            SourceHealthRegistry.get_shared_instance().report(
                "postgres", available=False, failure_reason=type(exc).__name__
            )
            raise
        SourceHealthRegistry.get_shared_instance().report("postgres", available=True)
        self._belief_store = belief_store
        self._contract: dict | None = contract

    def _get_contract(self) -> dict:
        """Load B13 contract YAML lazily (cached after first load)."""
        if self._contract is None:
            import pathlib
            import yaml
            # Walk up from this file to find the registry
            base = pathlib.Path(__file__).parents[2]
            contract_path = base / "registry" / "contract" / "contract.b13_contradiction_engine.yaml"
            self._contract = yaml.safe_load(contract_path.read_text())
        return self._contract

    def detect_divergence(
        self,
        indicator_id: str,
        predicted_per_asset: dict[str, float],
        actual_per_asset: dict[str, float],
        sigma_historical: dict[str, float],
    ) -> dict[str, float]:
        """Compute per-asset divergence: |actual - predicted| / sigma_historical.

        Returns dict {asset: sigma_float}. If sigma_historical for an asset is 0,
        divergence for that asset is 0.0 (avoids div-by-zero).

        Args:
            indicator_id: FRED indicator ID (e.g. "CPIAUCSL") — used for logging.
            predicted_per_asset: {asset: predicted_value} from Phase 87 transmission engine.
            actual_per_asset: {asset: actual_market_reaction} from VM101/VM86.
            sigma_historical: {asset: historical_stddev} for normalization.

        Returns:
            {asset: divergence_in_sigma}
        """
        result: dict[str, float] = {}
        for asset in predicted_per_asset:
            predicted = predicted_per_asset[asset]
            actual = actual_per_asset.get(asset, predicted)  # fallback to predicted = 0 sigma
            sigma_hist = sigma_historical.get(asset, 0.0)
            if sigma_hist == 0.0:
                result[asset] = 0.0
            else:
                result[asset] = abs(actual - predicted) / sigma_hist
        logger.debug({
            "event": "contradiction_divergence_computed",
            "indicator_id": indicator_id,
            "divergence_sigma": result,
        })
        return result

    def grade_severity(
        self,
        divergence_sigma_per_asset: dict[str, float],
        active_beliefs: list[dict],
    ) -> SeverityResult:
        """Grade severity per B13 contract rules (delegates to severity_grader).

        Args:
            divergence_sigma_per_asset: Per-asset sigma from detect_divergence().
            active_beliefs: Active BeliefStore beliefs for this indicator.

        Returns:
            SeverityResult with severity, triggers_fired, ui_surface,
            downstream_confidence_delta.
        """
        contract = self._get_contract()
        return grade_severity(
            divergence_sigma_per_asset=divergence_sigma_per_asset,
            active_beliefs=active_beliefs,
            contract=contract,
        )

    def active_blocking(self, indicator_id: str) -> bool:
        """Check if a blocking contradiction is active for the given indicator.

        PITFALL 2 CLOSED: This method reads Postgres DIRECTLY.
        It does NOT use BeliefStore query or Mongo cache.

        Returns True if there is at least one unresolved blocking contradiction
        for this indicator in the macro_contradictions table.

        Args:
            indicator_id: FRED indicator ID to check (e.g. "CPIAUCSL").

        Returns:
            True if active blocking contradiction exists; False otherwise.
        """
        try:
            with self._conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM macro_contradictions "
                    "WHERE indicator_id = %s AND severity = 'blocking' "
                    "AND unresolved = TRUE LIMIT 1",
                    (indicator_id,),
                )
                row = cur.fetchone()
            return row is not None
        except Exception as exc:
            logger.error({
                "event": "contradiction_active_blocking_error",
                "indicator_id": indicator_id,
                "error": str(exc),
            })
            # Fail open (return False) on DB error — do not block emit on infra failure
            return False

    def increment_contradicting_count(
        self,
        belief_id: str,
        contradiction_id: str,
    ) -> None:
        """Increment contradicting_count on the related BeliefStore belief.

        Calls BeliefStore.propose(confirms_belief=False, ...) per B13 contract wiring.

        Args:
            belief_id: UUID string of the related belief to update.
            contradiction_id: UUID string of the contradiction artifact.
        """
        belief_store = self._get_belief_store()
        belief_store.propose(
            proposer_id="macro_contradiction_detector",
            subject_type="indicator",
            subject_id=belief_id,  # uses belief_id as subject_id for the update
            confirms_belief=False,
            evidence={
                "contradiction_id": contradiction_id,
                "source": "macro_contradiction_detector",
            },
        )

    def _get_belief_store(self) -> Any:
        """Lazy BeliefStore construction (injectable for tests)."""
        if self._belief_store is None:
            from core.belief.belief_store import BeliefStore
            self._belief_store = BeliefStore()  # reads BELIEF_STORE_POSTGRES_URL + MONGO_URL from env
        return self._belief_store

    def write_contradiction(self, artifact: ContradictionArtifact) -> None:
        """Insert a ContradictionArtifact into the macro_contradictions Postgres table.

        Also triggers BeliefStore wiring for blocking severity (increments
        contradicting_count on the related belief if one is set).

        Args:
            artifact: Validated ContradictionArtifact to persist.
        """
        try:
            with self._conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO macro_contradictions (
                        contradiction_id, indicator_id, asset_keys,
                        predicted_value, actual_value, divergence_sigma,
                        severity, explanation_candidates, related_belief_id,
                        conflict_strength, unresolved, resolution_strategy,
                        resolution_artifact_id, detected_at, resolved_at
                    ) VALUES (
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s
                    )
                    """,
                    (
                        str(artifact.contradiction_id),
                        artifact.indicator_id,
                        artifact.asset_keys,
                        json.dumps(artifact.predicted_value),
                        json.dumps(artifact.actual_value),
                        json.dumps(artifact.divergence_sigma),
                        artifact.severity,
                        json.dumps(artifact.explanation_candidates),
                        str(artifact.related_belief_id) if artifact.related_belief_id else None,
                        artifact.conflict_strength,
                        artifact.unresolved,
                        artifact.resolution_strategy,
                        str(artifact.resolution_artifact_id) if artifact.resolution_artifact_id else None,
                        artifact.detected_at,
                        artifact.resolved_at,
                    ),
                )
            self._conn.commit()
            logger.info({
                "event": "contradiction_written",
                "contradiction_id": str(artifact.contradiction_id),
                "indicator_id": artifact.indicator_id,
                "severity": artifact.severity,
            })
        except Exception as exc:
            self._conn.rollback()
            logger.error({
                "event": "contradiction_write_error",
                "contradiction_id": str(artifact.contradiction_id),
                "error": str(exc),
            })
            raise

        # BeliefStore wiring: on blocking, increment contradicting_count
        if artifact.severity == "blocking" and artifact.related_belief_id:
            try:
                self.increment_contradicting_count(
                    belief_id=str(artifact.related_belief_id),
                    contradiction_id=str(artifact.contradiction_id),
                )
            except Exception as exc:
                # Belief wiring failure is non-fatal — log but don't rollback the artifact
                logger.error({
                    "event": "contradiction_belief_wiring_error",
                    "contradiction_id": str(artifact.contradiction_id),
                    "error": str(exc),
                })

    def close(self) -> None:
        """Close the Postgres connection."""
        try:
            self._conn.close()
        except Exception:
            pass
