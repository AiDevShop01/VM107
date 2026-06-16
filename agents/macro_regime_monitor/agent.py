"""Phase 87 Plan 10 (Wave 5b) — vm107.macro_regime_monitor background agent.

Every 6h (cron ``0 */6 * * *`` UTC) the runner CLI fires
``MacroRegimeMonitor.run_once()`` which:

  1. Pulls the current regime from the macro_regime_classification table
     (cold-start → ``"expansion"``).
  2. Pulls the last 12h of anchor indicator releases via the VM101 typed
     economic_event API (Phase 47.2 lock — NO parquet reads from VM107).
  3. For each release, calls ``BeliefStore.propose()`` for ALL 7 regimes
     (Brain Part 2 §B9 deterministic-proposer pathway; LLM-direct
     propose blocked by ``proposal_authorization.authorize_proposer``).
  4. Re-queries the 7 belief snapshots and asks
     ``skill_transition_detection.detect_max_transition`` for the
     highest-probability cross-regime candidate.
  5. If a candidate exceeds LOCK-3 0.65, checks LOCK-9 12h dedup window
     in the event store. If a same-(from,to) transition fired within
     12h, skip emission + notification (return existing event_id).
  6. Otherwise emit ``regime_transition_detected`` on the event store
     AND dispatch a Phase 74 macro-channel P2 Warning notification.

Ships as docker-compose sibling service ``vm107-macro-regime-monitor``
alongside Plan 87-08's ``vm107-macro-story-tracker`` per LOCK-8 /
REQ-87-8. Plan 87-14 deploy gate verifies both siblings survive
``docker compose restart vm107``.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from .dedup_window import is_in_dedup_window
from .phase74_notification_client import Phase74NotificationClient
from .skill_transition_detection import (
    REGIMES,
    TransitionDecision,
    detect_max_transition,
)


logger = logging.getLogger(__name__)


# Cold-start default — mirrors Plan 87-06 macro_regime_analyst's
# ``_COLD_START_DEFAULT_REGIME`` for consistency.
_COLD_START_DEFAULT_REGIME: str = "expansion"


class MacroRegimeMonitor:
    """6-hourly background agent re-evaluating regime probabilities."""

    agent_id: str = "vm107.macro_regime_monitor"
    proposer_id: str = "macro_regime_monitor"

    def __init__(
        self,
        *,
        belief_store: Any,                 # Plan 87-09 real BeliefStore
        anchor_release_poller: Any,        # VM101 typed economic_event API
        event_store: Any,                  # Phase 56 event store
        phase74_client: Phase74NotificationClient,
        classification_repo: Any,          # macro_regime_classification DAL
        cold_start_default_regime: str = _COLD_START_DEFAULT_REGIME,
    ) -> None:
        self._beliefs = belief_store
        self._poller = anchor_release_poller
        self._events = event_store
        self._p74 = phase74_client
        self._classifications = classification_repo
        self._cold_start = cold_start_default_regime

    # ── Public entry point ──────────────────────────────────────────────
    def run_once(self) -> dict:
        """Execute one tick of the monitor.

        Returns a stats dict describing the outcome (always returns —
        never raises for transition-flow conditions; only re-raises
        ``PermissionError`` from the proposal authorization gate which
        indicates a configuration bug).
        """
        current_regime = self._current_regime()
        releases = self._poller.poll_recent_releases(hours=12)
        releases_by_indicator = self._group_by_indicator(releases)

        # 1. Update belief probabilities for ALL 7 regimes from each release.
        #
        # Wave 5 contract: every release is evidence for the regime it
        # actually classifies, contradicting evidence for the other 6.
        # The simplified rule below uses ``current_regime`` as the
        # confirmation target — a deliberate Wave-5b simplification that
        # mirrors the Plan-07's Brain B6 cold-start behaviour. Phase 87
        # decimal-sibling work will refine this to per-release
        # classification (see RESEARCH §Wave-5).
        for release in releases:
            self._update_beliefs_for_release(release, current_regime)

        # 2. Re-query the 7 snapshots after the Bayesian update.
        snapshots = {
            regime: (self._beliefs.query(
                subject_type="regime", subject_id=regime,
            ) or {})
            for regime in REGIMES
        }

        # 3. Detect the highest-probability cross-regime transition.
        decision = detect_max_transition(
            belief_snapshots=snapshots,
            current_regime=current_regime,
            anchor_releases_last_12h=releases_by_indicator,
        )
        if decision is None:
            logger.info(
                {"event": "regime_monitor_tick",
                 "transition_detected": False,
                 "current_regime": current_regime}
            )
            return {"transition_detected": False,
                    "current_regime": current_regime}

        # 4. LOCK-9 dedup — same (from,to) transition fired in 12h?
        existing = is_in_dedup_window(
            event_store=self._events,
            from_regime=decision.from_regime,
            to_regime=decision.to_regime,
        )
        if existing:
            logger.info(
                {"event": "regime_monitor_tick",
                 "transition_detected": True,
                 "deduped": True,
                 "existing_event_id": existing}
            )
            return {"transition_detected": True, "deduped": True,
                    "existing_event_id": existing}

        # 5. Emit + notify.
        event_id = self._emit_transition_event(decision)
        try:
            self._p74.dispatch_transition(
                decision=decision, event_id=event_id,
            )
        except Exception as exc:  # noqa: BLE001
            # Notification failures must NOT cause the tick to crash;
            # the event has already been emitted (single source of truth).
            logger.exception(
                {"event": "phase74_dispatch_failed",
                 "event_id": event_id, "error": str(exc)}
            )

        logger.info(
            {"event": "regime_monitor_tick",
             "transition_detected": True,
             "event_id": event_id,
             "from_regime": decision.from_regime,
             "to_regime": decision.to_regime,
             "probability": decision.probability,
             "joint_pattern": decision.joint_pattern_detected}
        )
        return {
            "transition_detected": True,
            "event_id": event_id,
            "from_regime": decision.from_regime,
            "to_regime": decision.to_regime,
            "joint_pattern": decision.joint_pattern_detected,
        }

    # ── Helpers ─────────────────────────────────────────────────────────
    def _current_regime(self) -> str:
        try:
            recent = self._classifications.most_recent_regime()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                {"event": "classification_repo_query_failed",
                 "error": str(exc)}
            )
            return self._cold_start
        return recent or self._cold_start

    @staticmethod
    def _group_by_indicator(releases: list[dict]) -> dict[str, list[dict]]:
        grouped: dict[str, list[dict]] = {}
        for release in releases:
            indicator_id = release.get("indicator_id")
            if not indicator_id:
                continue
            grouped.setdefault(indicator_id, []).append(release)
        return grouped

    def _update_beliefs_for_release(
        self, release: dict, current_regime: str,
    ) -> None:
        evidence = {
            "release_id": release.get("release_id"),
            "indicator_id": release.get("indicator_id"),
        }
        for regime in REGIMES:
            confirms = (regime == current_regime)
            try:
                self._beliefs.propose(
                    proposer_id=self.proposer_id,
                    subject_type="regime",
                    subject_id=regime,
                    confirms_belief=confirms,
                    evidence=evidence,
                )
            except PermissionError:
                # authorize_proposer gate — surfaces a config bug; re-raise.
                logger.error(
                    {"event": "authorize_proposer_rejected",
                     "proposer_id": self.proposer_id,
                     "subject_id": regime}
                )
                raise

    def _emit_transition_event(self, decision: TransitionDecision) -> str:
        payload = {
            "event_id": str(uuid.uuid4()),
            "from_regime": decision.from_regime,
            "to_regime": decision.to_regime,
            "probability": float(decision.probability),
            "confidence": float(decision.confidence),
            "top_3_indicators": list(decision.top_3_indicators),
            "joint_pattern_detected": bool(decision.joint_pattern_detected),
            "triggering_belief_id": decision.triggering_belief_id,
            "detected_at": datetime.now(tz=timezone.utc).isoformat(),
        }
        event_id = self._events.emit(
            event_type="regime_transition_detected",
            payload=payload,
        )
        return str(event_id)
