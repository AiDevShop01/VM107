"""Phase 87 Wave 4b — macro_story_tracker hourly background agent.

Lifecycle of one ``run_once`` tick:

  1. Poll the last 6 hours of releases from VM101 (typed API; Phase 47.2 lock).
  2. Detect multi-indicator joint patterns (REQ-87-9; ``skill_multi_indicator_pattern``).
  3. Pull top-K=5 prior episodes via the Plan 87-07 ``message_loop_prompts_before_b6``
     helper bound against the real ``EpisodicMemoryService``.
  4. Build the narration prompt (release-line table + joint-pattern directive +
     episode block).
  5. Call the Phase 43 LLM router; parse a JSON list of candidate headlines.
  6. For each candidate: embed (Phase 58 EmbeddingService) → decide
     CREATE / REINFORCE / DROP via ``decide_update`` → persist + emit envelope.
  7. Retirement sweep across ALL active stories (LOCK-7) using last-12-week history.
  8. Publish ``macro.story.updated`` WS topic (thin-invalidation contract).

REQ-87-4 (≥3 active stories during normal market conditions) is verified by
Plan 87-14's 24h soak — this plan ships the lifecycle MACHINERY.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from .release_poller import ReleasePoller
from .skill_multi_indicator_pattern import (
    detect_joint_pattern,
    joint_pattern_prompt_directive,
)
from .skill_story_update import (
    StoryUpdateDecision,
    check_retirement,
    decide_update,
)

logger = logging.getLogger(__name__)


class MacroStoryTracker:
    """Phase 36 AgentRunner-compatible hourly background agent.

    All collaborators are injected via the constructor so the agent is
    fully unit-testable without a live Postgres / Qdrant / LLM router
    (see ``tests/phase87/test_story_tracker_b6_injection.py`` for the
    B6 wiring assertion).
    """

    agent_id = "vm107.macro_story_tracker"

    def __init__(
        self,
        *,
        poller: ReleasePoller,
        episodic_memory_service: Any,
        b6_hook: Any,
        llm_router: Any,
        embedding_service: Any,
        envelope_repo: Any,
        persist_repo: Any,
        ws_publisher: Any,
    ) -> None:
        self._poller = poller
        self._memory = episodic_memory_service
        self._b6 = b6_hook
        self._llm = llm_router
        self._embed = embedding_service
        self._envelope_repo = envelope_repo
        self._persist = persist_repo
        self._ws = ws_publisher

    def run_once(self) -> dict:
        """Execute one full hourly tick. Returns a stats dict."""
        stats = {"created": 0, "reinforced": 0, "retired": 0, "dropped": 0}

        releases = self._poller.poll_recent_releases(hours=6)
        if not releases:
            logger.info({"event": "story_tracker_no_releases"})
            return stats

        pattern = detect_joint_pattern(releases)
        active_stories = self._persist.list_active()

        query_text = self._summarise(releases, pattern)
        episode_block = self._b6(
            agent_profile_id=self.agent_id,
            query_text=query_text,
            episodic_memory_service=self._memory,
        )

        prompt = self._build_prompt(releases, pattern, episode_block)
        llm_out = self._llm.complete(prompt)
        candidates = self._parse_llm(llm_out)

        for cand in candidates:
            emb = self._embed.embed(cand["headline"])
            decision = decide_update(
                candidate_headline=cand["headline"],
                candidate_embedding=emb,
                candidate_confidence=cand.get("confidence", 0.0),
                supporting_release_id=cand.get("release_id", ""),
                supporting_indicators=cand.get("supporting_indicators", []),
                active_stories=active_stories,
                embedding_service=self._embed,
            )
            self._apply_decision(decision, cand, emb, pattern)
            self._bump_stats(stats, decision)

        # Retirement sweep (LOCK-7) — last 12 weeks of per-indicator history.
        recent_by_indicator = self._poll_recent_per_indicator(weeks_back=12)
        for s in self._persist.list_active():
            retire, reason = check_retirement(
                story=s,
                recent_releases_by_indicator=recent_by_indicator,
            )
            if retire:
                self._persist.retire(story_id=s["story_id"], reason=reason)
                stats["retired"] += 1

        try:
            self._ws.publish("macro.story.updated", payload=None)
        except Exception as exc:  # noqa: BLE001
            logger.warning({"event": "story_tracker_ws_publish_failed",
                            "error": str(exc)})

        logger.info({"event": "story_tracker_tick", **stats})
        return stats

    # ── helpers ─────────────────────────────────────────────────────────

    def _summarise(self, releases: list[dict], pattern: dict) -> str:
        indicators = sorted({r.get("indicator_id", "?") for r in releases})
        suffix = " (joint pattern detected)" if pattern.get("has_pattern") else ""
        return f"Last 6h releases: {', '.join(indicators)}{suffix}"

    def _build_prompt(
        self,
        releases: list[dict],
        pattern: dict,
        episode_block: str,
    ) -> str:
        release_lines = "\n".join(
            "- {ind} on {date}: actual {actual} forecast {forecast} surprise {surprise:+.2f}".format(
                ind=r.get("indicator_id", "?"),
                date=r.get("release_date", "?"),
                actual=r.get("actual"),
                forecast=r.get("forecast"),
                surprise=float(r.get("surprise", 0) or 0),
            )
            for r in releases
        )
        directive = joint_pattern_prompt_directive(pattern)
        return (
            f"{episode_block}\n\n"
            "You are the macro_story_tracker. Detect emerging narratives "
            "across these recent releases:\n\n"
            f"{release_lines}"
            f"{directive}\n\n"
            "Return JSON list: "
            "[{headline, confidence, release_id, supporting_indicators: [str]}]. "
            "Output JSON only."
        )

    def _parse_llm(self, raw: str) -> list[dict]:
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            logger.warning({"event": "story_tracker_llm_not_json",
                            "raw_prefix": str(raw)[:200]})
            return []
        if not isinstance(parsed, list):
            logger.warning({"event": "story_tracker_llm_not_list",
                            "type": type(parsed).__name__})
            return []
        return parsed

    def _apply_decision(
        self,
        decision: StoryUpdateDecision,
        cand: dict,
        emb: list[float],
        pattern: dict,
    ) -> None:
        if decision.action == "CREATE":
            envelope_id = self._envelope_repo.persist(
                analysis_kind="macro_story_create",
                payload={"headline": cand["headline"], "pattern": pattern},
            )
            self._persist.create(
                story_id=decision.story_id,
                headline=cand["headline"],
                headline_embedding=emb,
                supporting_releases=[cand.get("release_id")],
                supporting_indicators=cand.get("supporting_indicators", []),
                confidence=cand.get("confidence", 0.0),
                generated_by_envelope_id=envelope_id,
            )
        elif decision.action == "REINFORCE":
            self._persist.reinforce(
                story_id=decision.story_id,
                add_release_id=cand.get("release_id"),
                add_indicators=cand.get("supporting_indicators", []),
            )
        # DROP — nothing to persist; reason is logged via the decision.
        logger.info({"event": "story_decision",
                     "action": decision.action,
                     "story_id": str(decision.story_id),
                     "reason": decision.reason})

    def _bump_stats(self, stats: dict, decision: StoryUpdateDecision) -> None:
        key = {
            "CREATE": "created",
            "REINFORCE": "reinforced",
            "DROP": "dropped",
        }.get(decision.action)
        if key:
            stats[key] = stats.get(key, 0) + 1

    def _poll_recent_per_indicator(self, weeks_back: int) -> dict[str, list[dict]]:
        hours = weeks_back * 7 * 24
        releases = self._poller.poll_recent_releases(hours=hours)
        by_indicator: dict[str, list[dict]] = {}
        for r in sorted(releases, key=lambda x: x.get("release_date", "")):
            by_indicator.setdefault(r.get("indicator_id", "?"), []).append(r)
        return by_indicator
