"""Phase 173 (D-05) — MacroContradictionDetector thin agent.

Binds the built core/contradiction/ContradictionEngine (detect_divergence /
grade_severity / active_blocking / write_contradiction). This module is a
binding surface ONLY — all detection/grading/persistence logic lives in the
engine, which is fully built and tested at tests/phase89/. The thin agent
neither recomputes divergence nor re-grades severity: it wires a
release event to the engine, persists the resulting artifact, and fans a
warning/blocking contradiction out to the Phase 91 UAE.

Pattern mirrors agents.macro_indicator_alert_emitter for the agent surface
(class with an ``agent_id`` class attr, a DI ctor, one primary method, and a
module-level shim); alert fan-out uses core/alerts/phase91_emit.emit_alert_candidate
(shared with the emitter + discovery per the Phase 89 Wave 3 lock).

The engine ctor reads CONTRADICTION_POSTGRES_URL (fail-fast, no default) and
already reports to SourceHealthRegistry on connect — the thin agent does NOT
duplicate that health report; it lazily constructs the engine only when needed
so import + dispatch-reachability do not require a live Postgres. Tests inject a
fake engine via the DI ctor.

Architecture:

    Phase 85 release-completed event (reaction_settled_at <= now)
        → _dispatch_agent_sync
        → MacroContradictionDetector.emit_for_release(release_event)
            → engine.detect_divergence(...) → engine.grade_severity(...)
            → engine.write_contradiction(artifact)
            → warning/blocking: emit_alert_candidate(alert_type='contradiction', ...)

Tests: tests/agents/test_macro_contradiction_detector.py.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from core.alerts.phase91_emit import emit_alert_candidate
from core.contradiction.contradiction_engine import (
    ContradictionArtifact,
    ContradictionEngine,
)

logger = logging.getLogger(__name__)


class MacroContradictionDetector:
    """Thin agent binding the built B13 ContradictionEngine.

    Stateless surface — every call to emit_for_release delegates detection,
    grading, and persistence to the injected/lazy engine. The agent owns NO
    divergence or severity math.

    Args:
        engine: Inject a pre-built (or fake, in tests) ContradictionEngine.
            When None, the real engine is lazily constructed on first use
            (reads CONTRADICTION_POSTGRES_URL — fail-fast, no default) so
            import/dispatch-reachability never requires live Postgres.
        agent_id: Override the producer_agent_id used in the alert envelope.
    """

    agent_id: str = "vm107.macro_contradiction_detector"

    def __init__(
        self,
        *,
        engine: ContradictionEngine | None = None,
        agent_id: str | None = None,
    ) -> None:
        self._engine = engine
        # Ownership seam (CR-01): an engine this agent lazily constructs opens a
        # Postgres connection it must release; a DI-injected engine is owned by
        # the caller and is never closed here.
        self._owns_engine = engine is None
        if agent_id is not None:
            self.agent_id = agent_id

    def _get_engine(self) -> ContradictionEngine:
        """Lazily construct the real engine (injectable for tests)."""
        if self._engine is None:
            # Reads CONTRADICTION_POSTGRES_URL (fail-fast, no default); the
            # engine reports its own Postgres health on connect.
            self._engine = ContradictionEngine()
        return self._engine

    def close(self) -> None:
        """Release the lazily-constructed engine's Postgres connection (CR-01).

        Resource lifecycle only — no detection/grading/persistence logic. Closes
        an engine this agent constructed itself; a DI-injected engine is left
        untouched because its lifecycle belongs to the caller.
        """
        if self._owns_engine and self._engine is not None:
            close = getattr(self._engine, "close", None)
            if callable(close):
                close()
            self._engine = None

    def emit_for_release(self, release_event: dict[str, Any]) -> dict[str, Any]:
        """Grade one release event via the engine and fan out on contradiction.

        Args:
            release_event: Dict carrying at minimum ``indicator_id`` plus the
                engine inputs ``predicted_per_asset`` / ``actual_per_asset`` /
                ``sigma_historical`` (the Phase 87 transmission prediction vs the
                Phase 86 measured reaction). Optional: ``active_beliefs``,
                ``release_date``, ``related_belief_id``.

        Returns:
            Stats dict (mirrors the emitter return shape):
              - indicator_id (echo)
              - severity (engine grade — None when skipped)
              - emitted_count (int — alert candidates POSTed)
              - skipped_no_indicator (bool)
        """
        indicator_id = release_event.get("indicator_id")
        if not indicator_id:
            logger.warning({
                "event": "macro_contradiction_missing_indicator_id",
                "release_event_keys": sorted(release_event.keys()),
            })
            return {
                "indicator_id": None,
                "severity": None,
                "emitted_count": 0,
                "skipped_no_indicator": True,
            }

        predicted_per_asset = release_event.get("predicted_per_asset", {})
        actual_per_asset = release_event.get("actual_per_asset", {})
        sigma_historical = release_event.get("sigma_historical", {})
        active_beliefs = release_event.get("active_beliefs", [])
        release_date = release_event.get("release_date") or ""

        engine = self._get_engine()

        # 1-2. Delegate detection + grading to the engine (NO recompute here).
        divergence = engine.detect_divergence(
            indicator_id,
            predicted_per_asset,
            actual_per_asset,
            sigma_historical,
        )
        severity_result = engine.grade_severity(divergence, active_beliefs)
        severity = getattr(severity_result, "severity", None)

        # 3. Persist the artifact via the engine.
        related_belief_id = release_event.get("related_belief_id")
        conflict_strength = max(divergence.values(), default=0.0)
        artifact = ContradictionArtifact(
            contradiction_id=uuid4(),
            indicator_id=indicator_id,
            asset_keys=list(divergence.keys()),
            predicted_value=predicted_per_asset,
            actual_value=actual_per_asset,
            divergence_sigma=divergence,
            severity=severity if severity is not None else "info",
            related_belief_id=related_belief_id,
            conflict_strength=float(conflict_strength),
            unresolved=True,
            detected_at=datetime.now(tz=timezone.utc),
        )
        engine.write_contradiction(artifact)

        # 4. Fan a warning/blocking contradiction out to the Phase 91 UAE.
        emitted_count = 0
        if severity in ("warning", "blocking"):
            explanation = (
                f"{indicator_id}: contradiction graded {severity} "
                f"(max divergence {conflict_strength:.2f}σ across "
                f"{len(divergence)} asset(s))"
            )
            citation = f"release:{indicator_id}-{release_date}" if release_date else f"release:{indicator_id}"
            try:
                emit_alert_candidate(
                    alert_type="contradiction",
                    producer_agent_id=self.agent_id,
                    subject_id=indicator_id,
                    b13_internal_severity=severity,
                    explanation=explanation,
                    citations=[citation],
                    contradiction_id=artifact.contradiction_id,
                )
                emitted_count = 1
            except Exception as exc:  # noqa: BLE001
                logger.error({
                    "event": "macro_contradiction_emit_failed",
                    "indicator_id": indicator_id,
                    "severity": severity,
                    "error": str(exc),
                })

        logger.info({
            "event": "macro_contradiction_release_processed",
            "indicator_id": indicator_id,
            "severity": severity,
            "emitted_count": emitted_count,
        })
        return {
            "indicator_id": indicator_id,
            "severity": severity,
            "emitted_count": emitted_count,
            "skipped_no_indicator": False,
        }


# Module-level shim so the Phase 85 dispatcher (or an external caller) can fire
# without instantiating the class.
def emit_for_release(release_event: dict[str, Any]) -> dict[str, Any]:
    """Module-level convenience wrapper — MacroContradictionDetector().emit_for_release.

    Owns the engine it lazily constructs, so it releases the per-call Postgres
    connection on every path — success AND exception (CR-01) — to avoid leaking
    one connection per event for the life of the long-running VM107 process.
    """
    detector = MacroContradictionDetector()
    try:
        return detector.emit_for_release(release_event)
    finally:
        detector.close()


__all__ = ["MacroContradictionDetector", "emit_for_release"]
