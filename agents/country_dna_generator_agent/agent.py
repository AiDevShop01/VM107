"""Phase 96 Plan 05 — CountryDnaGenerator agent (REQ-96-4).

Hybrid Neo4j + Qdrant pipeline that emits 5-10 structural economic-DNA tags
per country with provenance. Replaces the Phase 94-07 ``_DEFAULT_DNA_TAGS``
heuristic that hard-coded the same 3 tags for every country.

Pipeline:
    1. Qdrant retrieval — for each STRUCTURAL_QUERY_TEMPLATE, query the
       country_profiles collection filtered to the template's section_type
       and the target country's ISO. The top hit must score >= the template's
       ``min_score`` to be a candidate.
    2. Neo4j confirmation — for each candidate, walk the country subgraph via
       ``graph_tool.run_template('find_country_subgraph', iso_alpha2=..., depth=2)``
       and apply the template's ``graph_predicate`` against the returned paths.
       If at least one path matches, the candidate is confirmed.
    3. Emit — confirmed candidates produce a ``EconomicDnaTag`` with:
           - ``provenance_sections`` = top-3 Qdrant section IDs
           - ``provenance_graph_paths`` = top-3 Cypher path signatures
           - ``confidence`` = blended Qdrant score + graph-path count + baseline

Output cap: 10 tags (sorted by confidence desc). No floor enforcement —
if fewer than 5 candidates pass, agent logs a warning and ships what it has
(the caller fail-soft handles via VM100/api/world/section_resolvers/country_dna.py).

Event emission: every successful invoke emits a ``country_dna_tag_recomputed``
event (Plan 04 registry entry) via the injected ``event_emitter`` (None-safe
for in-process tests).

Env locks (feedback_env_driven_no_fallbacks):
    NEO4J_URI / QDRANT_URL are mandatory at constructor time when calling
    ``from_env()``. The DI-friendly ``__init__`` takes pre-built tools so
    tests can mock both ends without env touching.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Iterable

from contracts.economic_intelligence.economic_dna_tag import EconomicDnaTag

from agents.country_dna_generator_agent.qdrant_query_templates import (
    STRUCTURAL_QUERY_TEMPLATES,
)


logger = logging.getLogger("agents.country_dna_generator_agent")


# Output discipline (mirrors profile.yaml — kept here as runtime constants so
# the agent never needs to read its own YAML at request time).
_OUTPUT_CEILING = 10
_PROVENANCE_CAP = 3
_GRAPH_TEMPLATE_NAME = "find_country_subgraph"
_GRAPH_DEPTH = 2


class CountryDnaGenerator:
    """Hybrid Neo4j + Qdrant DNA tag generator (REQ-96-4).

    Public API:
        invoke(iso, profile_summary) -> list[EconomicDnaTag]

    Construction:
        - ``CountryDnaGenerator(qdrant_tool, graph_tool)`` — DI-friendly; tests
          inject pre-built mocks and never touch env vars (still call ``from_env``
          to exercise the fail-fast path).
        - ``CountryDnaGenerator.from_env()`` — production path. Builds the
          ``FindCountriesByProfileQueryTool`` (Plan 06) + ``GraphSearchTool`` from
          env-resolved URIs. Raises ``KeyError`` if NEO4J_URI / QDRANT_URL are
          missing (feedback_env_driven_no_fallbacks).

    Event emission:
        Pass ``event_emitter`` with an ``.emit(event_type=..., payload=...)`` method
        (Phase 74 NotificationDispatcher style). When omitted, event emission is
        skipped (in-process / test path); a debug log line still fires.
    """

    AGENT_ID = "vm107.country_dna_generator"
    IMPACT_ON_DECISION = "MEDIUM"  # Registry CONTEXT lock (Plan 04)
    EVENT_TYPE_RECOMPUTED = "country_dna_tag_recomputed"

    def __init__(
        self,
        qdrant_tool: Any,
        graph_tool: Any,
        *,
        event_emitter: Any | None = None,
        settings: dict | None = None,
    ) -> None:
        self.qdrant = qdrant_tool
        self.graph = graph_tool
        self.event_emitter = event_emitter
        self.settings = settings or {}

    # ------------------------------------------------------------------
    # Construction — production path
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> "CountryDnaGenerator":
        """Build the agent from env-resolved tools.

        Fail-fast: NEO4J_URI / QDRANT_URL missing → ``KeyError``. No silent
        defaults (feedback_env_driven_no_fallbacks). Tool construction is
        deferred to the helpers below so callers can monkeypatch them per-test.
        """
        # KeyError-style fail-fast — direct subscription, not .get(...).
        _ = os.environ["NEO4J_URI"]
        _ = os.environ["QDRANT_URL"]

        qdrant_tool = cls._build_qdrant_tool()
        graph_tool = cls._build_graph_tool()
        return cls(qdrant_tool=qdrant_tool, graph_tool=graph_tool)

    @staticmethod
    def _build_qdrant_tool() -> Any:
        """Lazy import the Plan 06 tool so the agent module imports cleanly
        even when qdrant_client isn't installed in the test environment."""
        from tools.find_countries_by_profile_query import (
            FindCountriesByProfileQueryTool,
        )

        return FindCountriesByProfileQueryTool()

    @staticmethod
    def _build_graph_tool() -> Any:
        """Lazy import GraphSearchTool — Plan 11 adds the find_country_subgraph
        template; until then the agent gracefully degrades (no paths → no tag)."""
        from tools.graph.graph_search_tool import GraphSearchTool

        return GraphSearchTool()

    # ------------------------------------------------------------------
    # Public invoke
    # ------------------------------------------------------------------

    def invoke(
        self, iso: str, profile_summary: dict | None = None
    ) -> list[EconomicDnaTag]:
        """Run the hybrid pipeline against ``iso`` and return DNA tags.

        Args:
            iso: ISO 3166-1 alpha-2 country code (UPPERCASE).
            profile_summary: optional pre-fetched profile dict (passed to the
                event payload + future LLM prompt; not required for current
                deterministic template path).

        Returns:
            list[EconomicDnaTag] sorted by confidence desc, capped at 10.

        Never raises — graph / Qdrant exceptions degrade to "skip this template".
        """
        iso = (iso or "").upper()
        profile_summary = profile_summary or {}

        candidates: list[EconomicDnaTag] = []
        for tmpl in STRUCTURAL_QUERY_TEMPLATES:
            tag = self._evaluate_template(tmpl, iso)
            if tag is not None:
                candidates.append(tag)

        # Sort by confidence desc; cap at ceiling.
        candidates.sort(key=lambda t: t.confidence, reverse=True)
        capped = candidates[:_OUTPUT_CEILING]

        if len(capped) < 5:
            logger.warning(
                "country_dna_generator.under_floor",
                extra={
                    "iso": iso,
                    "tag_count": len(capped),
                    "floor": 5,
                    "tags": [t.tag_id for t in capped],
                },
            )

        self._emit_recomputed(iso=iso, tag_count=len(capped))
        return capped

    # ------------------------------------------------------------------
    # Internals — per-template evaluation
    # ------------------------------------------------------------------

    def _evaluate_template(
        self, tmpl: dict, iso: str
    ) -> EconomicDnaTag | None:
        """Run Qdrant + Neo4j confirmation for one template; return tag or None."""
        # --- Qdrant retrieval ---
        try:
            hits = self.qdrant.run(
                query=tmpl["query"],
                section_filter=tmpl["section"],
                country=iso,
            )
        except Exception as exc:  # graceful degradation
            logger.warning(
                "country_dna_generator.qdrant_failed",
                extra={"iso": iso, "tag_id": tmpl["tag_id"], "error": str(exc)},
            )
            return None

        hits = list(hits or [])
        if not hits:
            return None

        top_hit = hits[0]
        top_score = float(getattr(top_hit, "score", 0.0))
        if top_score < tmpl["min_score"]:
            return None

        # --- Neo4j confirmation ---
        try:
            graph_paths = self.graph.run_template(
                _GRAPH_TEMPLATE_NAME,
                iso_alpha2=iso,
                depth=_GRAPH_DEPTH,
                tag_id=tmpl["tag_id"],
            )
        except TypeError:
            # Older graph tool signature — try without extra kwargs.
            try:
                graph_paths = self.graph.run_template(
                    _GRAPH_TEMPLATE_NAME, iso_alpha2=iso
                )
            except Exception as exc:
                logger.warning(
                    "country_dna_generator.graph_failed",
                    extra={"iso": iso, "tag_id": tmpl["tag_id"], "error": str(exc)},
                )
                return None
        except Exception as exc:
            logger.warning(
                "country_dna_generator.graph_failed",
                extra={"iso": iso, "tag_id": tmpl["tag_id"], "error": str(exc)},
            )
            return None

        graph_paths = list(graph_paths or [])
        if not self._confirms_tag(tmpl, graph_paths):
            return None

        # --- Emit ---
        section_ids = self._extract_section_ids(hits[:_PROVENANCE_CAP])
        path_sigs = self._extract_path_signatures(graph_paths[:_PROVENANCE_CAP])

        if not section_ids or not path_sigs:
            return None

        confidence = self._combined_score(
            qdrant_score=top_score,
            graph_path_count=len(graph_paths),
            baseline=tmpl.get("baseline_confidence", 0.5),
        )

        return EconomicDnaTag(
            tag_id=tmpl["tag_id"],
            label=tmpl["label"],
            confidence=confidence,
            provenance_sections=section_ids,
            provenance_graph_paths=path_sigs,
        )

    @staticmethod
    def _confirms_tag(tmpl: dict, graph_paths: list) -> bool:
        """Apply the template's graph_predicate against the returned paths.

        All current templates use ``any_outgoing`` — at least one outgoing
        Cypher path must exist. Plan 11's find_country_subgraph + the
        domain-specific predicates (commodity-exporter requires an
        EXPORTS_TO edge with a commodity-dominated payload, etc.) will land
        the more precise predicates in subsequent plans. For now: at least one
        path = confirmed.
        """
        predicate = tmpl.get("graph_predicate", "any_outgoing")
        if predicate == "any_outgoing":
            return len(graph_paths) >= 1
        # Unknown predicate → conservative: require at least one path.
        return len(graph_paths) >= 1

    @staticmethod
    def _extract_section_ids(hits: Iterable) -> list[int]:
        """Pull ``section_id`` off each hit, drop non-ints, dedupe preserving order."""
        seen: set[int] = set()
        out: list[int] = []
        for h in hits:
            sid = getattr(h, "section_id", None)
            if isinstance(sid, int) and sid not in seen:
                seen.add(sid)
                out.append(sid)
        return out

    @staticmethod
    def _extract_path_signatures(paths: Iterable) -> list[str]:
        """Pull ``signature`` off each path (Cypher-style string); drop empties."""
        out: list[str] = []
        for p in paths:
            sig = getattr(p, "signature", None)
            if isinstance(sig, str) and sig:
                out.append(sig)
        return out

    @staticmethod
    def _combined_score(
        *, qdrant_score: float, graph_path_count: int, baseline: float
    ) -> float:
        """Blend Qdrant score + graph evidence + baseline into a (0,1) confidence.

        Formula: 0.4 * qdrant_score + 0.4 * min(graph_path_count/3, 1.0) + 0.2 * baseline
        Clamped to (0.01, 0.99) so we never emit 0.0 / 1.0 for non-trivial tags
        (test_confidence_in_strict_open_unit_interval lock).
        """
        graph_evidence = min(max(graph_path_count, 0) / 3.0, 1.0)
        raw = 0.4 * qdrant_score + 0.4 * graph_evidence + 0.2 * baseline
        # Strict open interval — clamp.
        return max(0.01, min(0.99, raw))

    # ------------------------------------------------------------------
    # Event emission
    # ------------------------------------------------------------------

    def _emit_recomputed(self, *, iso: str, tag_count: int) -> None:
        """Emit ``country_dna_tag_recomputed`` (Plan 04 registry event_type).

        Payload (matches event_type YAML):
            - iso_alpha2: 2-letter country code
            - tag_count: int 0..50
            - recomputed_at: ISO-8601 UTC timestamp
            - trigger_source: 'manual' (default for in-process invocation)
        """
        from datetime import datetime, timezone

        payload = {
            "iso_alpha2": iso,
            "tag_count": tag_count,
            "recomputed_at": datetime.now(timezone.utc).isoformat(),
            "trigger_source": "manual",
        }

        if self.event_emitter is None:
            logger.debug(
                "country_dna_generator.event_skipped_no_emitter",
                extra=payload,
            )
            return

        try:
            self.event_emitter.emit(
                event_type=self.EVENT_TYPE_RECOMPUTED,
                payload=payload,
            )
        except Exception as exc:  # graceful — emit failures never crash agent
            logger.warning(
                "country_dna_generator.event_emit_failed",
                extra={"iso": iso, "error": str(exc)},
            )


__all__ = ["CountryDnaGenerator", "STRUCTURAL_QUERY_TEMPLATES"]
