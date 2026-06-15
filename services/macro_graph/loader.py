"""Phase 87 Wave 1 — Macro graph seed loader.

Pure-Python service class.  Reads the hand-curated YAML, calls the
CorrelationAugmenter for each edge, and MERGEs the result into Neo4j.

Idempotent per Phase 58 Pattern 5 — every write uses MERGE + ON CREATE / ON
MATCH SET, so a second run produces zero new constraints, zero new nodes,
and zero new edges (REQ-87-1b).
"""
from __future__ import annotations

import logging
import pathlib
from dataclasses import dataclass, field
from typing import Any

import neo4j
import yaml

from .correlation_augmentation import (
    AffectsEdge,
    CorrelationAugmenter,
    DrivesEdge,
)

logger = logging.getLogger(__name__)


@dataclass
class LoadReport:
    """Per-run counters returned by `MacroGraphLoader.load()`."""

    indicators_created: int = 0
    indicators_unchanged: int = 0
    affects_created: int = 0
    affects_unchanged: int = 0
    drives_created: int = 0
    drives_unchanged: int = 0
    degraded_edges: int = 0
    cypher_log: list[str] = field(default_factory=list)


class MacroGraphLoader:
    """Idempotent MERGE loader for the Phase 87 macro graph seed."""

    def __init__(
        self,
        seed_yaml_path: pathlib.Path,
        augmenter: CorrelationAugmenter,
        neo4j_driver: neo4j.Driver | None,
    ):
        self._yaml = yaml.safe_load(pathlib.Path(seed_yaml_path).read_text())
        self._augmenter = augmenter
        self._driver = neo4j_driver

    # ── Schema gate ──────────────────────────────────────────────────────────
    def _check_schema(self) -> None:
        if self._driver is None:
            raise RuntimeError(
                "Neo4j driver is None — cannot check schema in dry-run mode"
            )
        with self._driver.session() as session:
            rows = session.run(
                "SHOW CONSTRAINTS YIELD name WHERE name STARTS WITH 'macro_' "
                "OR name STARTS WITH 'asset_' RETURN name"
            ).data()
            if len(rows) < 2:
                raise RuntimeError(
                    "Macro schema missing — apply "
                    "vm105/migrations/0087_macro_graph_schema.cypher first "
                    "(Plan 87-02)"
                )

    # ── Driver entry point ──────────────────────────────────────────────────
    def load(self, *, dry_run: bool = False, check_schema: bool = True) -> LoadReport:
        if check_schema and not dry_run:
            self._check_schema()

        report = LoadReport()
        # Pass 1: MERGE every named indicator first so the indicator counter
        # reflects true intent (otherwise an AFFECTS edge MERGE can implicitly
        # create the target indicator and the later explicit MERGE then reads
        # as "unchanged", under-counting indicators_created).
        for ind in self._yaml["indicators"]:
            self._upsert_indicator(ind, dry_run=dry_run, report=report)

        # Pass 2: MERGE all edges.
        for ind in self._yaml["indicators"]:
            for edge_dict in ind.get("affects_chain", []):
                fallback = AffectsEdge(
                    source=ind["id"],
                    target=edge_dict["target"],
                    hop_order=int(edge_dict.get("hop_order", 0)),
                    strength=float(edge_dict["strength"]),
                    confidence=float(edge_dict["confidence"]),
                    sample_size=int(edge_dict["sample_size"]),
                    evidence_period=str(edge_dict["evidence_period"]),
                )
                augmented = self._augmenter.augment_affects(
                    source=fallback.source,
                    target=fallback.target,
                    yaml_fallback=fallback,
                )
                if augmented.degraded:
                    report.degraded_edges += 1
                self._upsert_affects(augmented, dry_run=dry_run, report=report)
            for edge_dict in ind.get("drives", []):
                fallback = DrivesEdge(
                    source=ind["id"],
                    target=edge_dict["asset"],
                    direction=str(edge_dict["direction"]),
                    strength=float(edge_dict["strength"]),
                    confidence=float(edge_dict["confidence"]),
                    sample_size=int(edge_dict["sample_size"]),
                    evidence_period=str(edge_dict["evidence_period"]),
                )
                augmented = self._augmenter.augment_drives(
                    source=fallback.source,
                    target_symbol=fallback.target,
                    yaml_fallback=fallback,
                )
                if augmented.degraded:
                    report.degraded_edges += 1
                self._upsert_drives(augmented, dry_run=dry_run, report=report)
        return report

    # ── Upsert primitives ──────────────────────────────────────────────────
    def _upsert_indicator(
        self, ind: dict[str, Any], *, dry_run: bool, report: LoadReport
    ) -> None:
        cypher = (
            "MERGE (i:MacroIndicator {id: $id}) "
            "ON CREATE SET i.name = $name, i.category = $cat, "
            "              i.release_cadence = $cadence "
            "ON MATCH SET  i.name = $name, i.category = $cat, "
            "              i.release_cadence = $cadence"
        )
        params = {
            "id": ind["id"],
            "name": ind["name"],
            "cat": ind["category"],
            "cadence": ind["release_cadence"],
        }
        if dry_run:
            report.cypher_log.append(f"{cypher}  :: params={params}")
            return
        with self._driver.session() as session:
            summary = session.run(cypher, **params).consume()
            if summary.counters.nodes_created:
                report.indicators_created += 1
            else:
                report.indicators_unchanged += 1

    def _upsert_affects(
        self, e: AffectsEdge, *, dry_run: bool, report: LoadReport
    ) -> None:
        cypher = (
            "MERGE (s:MacroIndicator {id: $src}) "
            "MERGE (t:MacroIndicator {id: $dst}) "
            "MERGE (s)-[r:AFFECTS]->(t) "
            "ON CREATE SET r.strength=$str, r.confidence=$conf, "
            "              r.sample_size=$n, r.evidence_period=$period, "
            "              r.hop_order=$hop, r.curation_source=$src_curation, "
            "              r.degraded=$degraded "
            "ON MATCH SET  r.strength=$str, r.confidence=$conf, "
            "              r.sample_size=$n, r.evidence_period=$period, "
            "              r.hop_order=$hop, r.curation_source=$src_curation, "
            "              r.degraded=$degraded"
        )
        params = {
            "src": e.source,
            "dst": e.target,
            "str": e.strength,
            "conf": e.confidence,
            "n": e.sample_size,
            "period": e.evidence_period,
            "hop": e.hop_order,
            "src_curation": e.curation_source,
            "degraded": e.degraded,
        }
        if dry_run:
            report.cypher_log.append(f"{cypher}  :: params={params}")
            return
        with self._driver.session() as session:
            summary = session.run(cypher, **params).consume()
            if summary.counters.relationships_created:
                report.affects_created += 1
            else:
                report.affects_unchanged += 1

    def _upsert_drives(
        self, e: DrivesEdge, *, dry_run: bool, report: LoadReport
    ) -> None:
        cypher = (
            "MERGE (s:MacroIndicator {id: $src}) "
            "MERGE (a:Asset {symbol: $dst}) "
            "MERGE (s)-[r:DRIVES]->(a) "
            "ON CREATE SET r.direction=$dir, r.strength=$str, r.confidence=$conf, "
            "              r.sample_size=$n, r.evidence_period=$period, "
            "              r.curation_source=$src_curation, r.degraded=$degraded "
            "ON MATCH SET  r.direction=$dir, r.strength=$str, r.confidence=$conf, "
            "              r.sample_size=$n, r.evidence_period=$period, "
            "              r.curation_source=$src_curation, r.degraded=$degraded"
        )
        params = {
            "src": e.source,
            "dst": e.target,
            "dir": e.direction,
            "str": e.strength,
            "conf": e.confidence,
            "n": e.sample_size,
            "period": e.evidence_period,
            "src_curation": e.curation_source,
            "degraded": e.degraded,
        }
        if dry_run:
            report.cypher_log.append(f"{cypher}  :: params={params}")
            return
        with self._driver.session() as session:
            summary = session.run(cypher, **params).consume()
            if summary.counters.relationships_created:
                report.drives_created += 1
            else:
                report.drives_unchanged += 1
