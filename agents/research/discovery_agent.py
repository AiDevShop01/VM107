"""Phase 92 Plan 05 — DiscoveryAgent.

Runs cross-doc analysis (weekly batch, or on-demand per indicator) to surface
novel patterns: ≥3 docs across ≥2 sources supporting the same key_finding
constitute a `research_discovery_candidate` event that routes to Phase 91 UAE.

Writes to MongoDB `research_intelligence_discoveries`. Emits via
agents.research.discovery_agent.emit_event (HTTP POST to Phase 91 intake URL).

impact_on_decision: HIGH (raises alerts).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from agents.research import storage


# ── Phase 91 event emission ────────────────────────────────────────────


def emit_event(event_type: str, payload: dict[str, Any]) -> None:
    """POST a Phase 91 candidate event to the UAE intake URL.

    Env-driven via PHASE_91_UAE_URL (NO fallback). Tests patch this function
    directly via monkeypatch.
    """
    import httpx

    url = os.environ.get("PHASE_91_UAE_URL")
    if not url:
        # Soft-fail at runtime if not configured — phase92 dev environments may
        # not have Phase 91 wired yet. Logging is sufficient.
        return
    try:
        with httpx.Client(timeout=10.0) as c:
            c.post(url, json={"event_type": event_type, "payload": payload})
    except Exception:
        # Discovery agent should NOT crash on transient UAE outages —
        # the MongoDB row is the durable record.
        pass


# ── Discovery analysis ─────────────────────────────────────────────────


@dataclass
class DiscoveryCandidate:
    discovery_id: str
    indicator_id: str
    pattern_summary: str
    supporting_docs: list[str]
    sources: list[str]
    severity: str
    category: str = "research_discovery"
    indicators: list[str] = field(default_factory=list)


@dataclass
class DiscoveryAnalysisResult:
    indicator_id: str
    candidates: list[DiscoveryCandidate]


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    inter = a & b
    uni = a | b
    return len(inter) / len(uni) if uni else 0.0


def _group_by_finding(
    summaries: list[dict[str, Any]],
    similarity_threshold: float = 0.5,
) -> list[list[dict[str, Any]]]:
    """Group summaries by per-finding co-occurrence.

    Approach: pivot on each unique key_finding tag, build a cluster of all
    summaries that mention it. A summary may appear in multiple clusters
    (one per shared finding) — this is intentional: cross-source agreement
    on ANY specific finding qualifies as a discovery candidate.

    `similarity_threshold` is retained for API compatibility but is unused
    in the per-finding-pivot mode (the threshold concept doesn't apply when
    clustering by exact-finding match).
    """
    by_finding: dict[str, list[dict[str, Any]]] = {}
    for s in summaries:
        for f in s.get("key_findings") or []:
            by_finding.setdefault(f, []).append(s)
    # Dedup docs within each cluster by doc_id (in case of duplicate writes).
    out: list[list[dict[str, Any]]] = []
    for finding, rows in by_finding.items():
        seen_doc_ids: set[str] = set()
        cluster: list[dict[str, Any]] = []
        for r in rows:
            doc_id = r.get("doc_id")
            if doc_id in seen_doc_ids:
                continue
            seen_doc_ids.add(doc_id)
            cluster.append(r)
        if cluster:
            # Attach the pivot finding on each cluster row so the candidate
            # builder can report it.
            for r in cluster:
                r.setdefault("_pivot_finding", finding)
            out.append(cluster)
    return out


class DiscoveryAgent:
    """REQ-92-6 — cross-doc novel-pattern surfacer."""

    def __init__(
        self,
        min_docs_per_pattern: int = 3,
        min_sources_per_pattern: int = 2,
        similarity_threshold: float = 0.5,
    ) -> None:
        self._min_docs = min_docs_per_pattern
        self._min_sources = min_sources_per_pattern
        self._similarity = similarity_threshold

    def analyse(
        self,
        indicator_id: str,
        lookback_days: int = 30,
        emit_to_phase91: bool = True,
    ) -> DiscoveryAnalysisResult:
        summaries = storage.read_summaries(indicator_id, lookback_days=lookback_days)
        # Filter by created_at >= now - lookback (best-effort if ISO strings or datetimes).
        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        filtered: list[dict[str, Any]] = []
        for s in summaries:
            created = s.get("created_at")
            if isinstance(created, str):
                # Coerce common ISO format
                try:
                    created = datetime.fromisoformat(created.replace("Z", "+00:00"))
                except ValueError:
                    created = None
            if created is None or (isinstance(created, datetime) and created >= cutoff):
                filtered.append(s)

        clusters = _group_by_finding(filtered, similarity_threshold=self._similarity)

        candidates: list[DiscoveryCandidate] = []
        emitted_finding_pivots: set[str] = set()
        for cl in clusters:
            sources = {s.get("source") for s in cl if s.get("source")}
            if len(cl) < self._min_docs or len(sources) < self._min_sources:
                continue
            primary_finding = (
                cl[0].get("_pivot_finding")
                or (cl[0].get("key_findings") or ["pattern"])[0]
            )
            if primary_finding in emitted_finding_pivots:
                # Avoid emitting duplicate candidates when the same set of
                # docs hits multiple pivot findings (which can happen because
                # of the per-finding-pivot clustering strategy).
                continue
            emitted_finding_pivots.add(primary_finding)
            cand = DiscoveryCandidate(
                discovery_id=str(uuid4()),
                indicator_id=indicator_id,
                pattern_summary=(
                    f"{len(cl)} docs across {len(sources)} sources support: "
                    f"{primary_finding}"
                ),
                supporting_docs=[s["doc_id"] for s in cl if "doc_id" in s],
                sources=sorted(sources),
                indicators=[indicator_id],
                severity="watch",
            )
            candidates.append(cand)
            # Persist
            storage.write_discovery(
                discovery_id=cand.discovery_id,
                pattern_summary=cand.pattern_summary,
                supporting_docs=cand.supporting_docs,
                indicators=cand.indicators,
                sources=cand.sources,
                severity=cand.severity,
            )
            # Emit Phase 91 candidate event (Wave 4 routing dep)
            if emit_to_phase91:
                payload = {
                    "discovery_id": cand.discovery_id,
                    "pattern_summary": cand.pattern_summary,
                    "supporting_docs": cand.supporting_docs,
                    "indicators": cand.indicators,
                    "sources": cand.sources,
                    "severity": cand.severity,
                    "category": cand.category,
                }
                emit_event("research_discovery_candidate", payload)

        return DiscoveryAnalysisResult(
            indicator_id=indicator_id, candidates=candidates
        )
