"""Wave 1 loader integration — load minimal seed into testcontainers Neo4j;
assert REQ-87-1-shape counts hold on the 3-indicator test fixture (>=6 AFFECTS
+ >=4 DRIVES per Plan 87-01). The FULL 12-indicator seed runs against
testcontainers in test_macro_graph_loader_idempotent.py (Task 3).
"""
from __future__ import annotations

import pathlib

import pytest

from services.macro_graph.correlation_augmentation import CorrelationAugmenter
from services.macro_graph.loader import MacroGraphLoader

pytestmark = pytest.mark.phase_87


class _NullAugmenter(CorrelationAugmenter):
    """Test double — never calls VM102; always returns the YAML fallback degraded."""

    def __init__(self):
        # bypass parent __init__ env check; no VM102 calls in this test
        pass

    def augment_affects(self, **kwargs):
        from dataclasses import replace
        return replace(kwargs["yaml_fallback"], degraded=True)

    def augment_drives(self, **kwargs):
        from dataclasses import replace
        return replace(kwargs["yaml_fallback"], degraded=True)


def test_loader_against_minimal_seed_yaml(neo4j_test_driver):
    """Use the Plan 87-01 minimal test fixture, not the full Wave 1 seed."""
    fixture_path = (
        pathlib.Path(__file__).parent / "fixtures" / "macro_graph_seed_test.yaml"
    )
    loader = MacroGraphLoader(
        seed_yaml_path=fixture_path,
        augmenter=_NullAugmenter(),
        neo4j_driver=neo4j_test_driver,
    )
    report = loader.load(dry_run=False, check_schema=True)
    assert report.indicators_created == 3
    assert report.affects_created >= 6
    assert report.drives_created >= 4

    # Now assert via Cypher directly
    with neo4j_test_driver.session() as session:
        affects_count = session.run(
            "MATCH ()-[r:AFFECTS]->() RETURN count(r) AS c"
        ).single()["c"]
        drives_count = session.run(
            "MATCH ()-[r:DRIVES]->() RETURN count(r) AS c"
        ).single()["c"]
    assert affects_count >= 6, f"expected >=6 AFFECTS, got {affects_count}"
    assert drives_count >= 4, f"expected >=4 DRIVES, got {drives_count}"


def test_loader_dry_run_does_not_write(neo4j_test_driver):
    fixture_path = (
        pathlib.Path(__file__).parent / "fixtures" / "macro_graph_seed_test.yaml"
    )
    loader = MacroGraphLoader(
        seed_yaml_path=fixture_path,
        augmenter=_NullAugmenter(),
        neo4j_driver=neo4j_test_driver,
    )

    # Snapshot edge counts before dry-run
    with neo4j_test_driver.session() as session:
        before_affects = session.run(
            "MATCH ()-[r:AFFECTS]->() RETURN count(r) AS c"
        ).single()["c"]

    report = loader.load(dry_run=True, check_schema=False)
    assert len(report.cypher_log) > 0, "dry-run must emit Cypher to log"

    # Confirm Neo4j was not mutated by the dry-run
    with neo4j_test_driver.session() as session:
        after_affects = session.run(
            "MATCH ()-[r:AFFECTS]->() RETURN count(r) AS c"
        ).single()["c"]
    assert before_affects == after_affects, "dry-run must not write to Neo4j"


def test_loader_check_schema_first_errors_on_missing_schema(tmp_path):
    """Loader with --check-schema-first against an empty Neo4j errors clearly."""
    from testcontainers.neo4j import Neo4jContainer

    with Neo4jContainer("neo4j:5.15") as neo4j_empty:
        driver = neo4j_empty.get_driver()
        try:
            fixture_path = (
                pathlib.Path(__file__).parent
                / "fixtures"
                / "macro_graph_seed_test.yaml"
            )
            loader = MacroGraphLoader(
                seed_yaml_path=fixture_path,
                augmenter=_NullAugmenter(),
                neo4j_driver=driver,
            )
            with pytest.raises(RuntimeError, match="Macro schema missing"):
                loader.load(dry_run=False, check_schema=True)
        finally:
            driver.close()


def test_correlation_augmenter_requires_vm102_base_url():
    """Augmenter fails-fast when VM102_BASE_URL is empty — no os.getenv default."""
    with pytest.raises(RuntimeError, match="VM102_BASE_URL"):
        CorrelationAugmenter(vm102_base_url="")


def test_correlation_augmenter_degrades_gracefully_on_connection_error():
    """When VM102 is unreachable the augmenter returns yaml_fallback with degraded=True."""
    from services.macro_graph.correlation_augmentation import AffectsEdge

    aug = CorrelationAugmenter(
        vm102_base_url="http://127.0.0.1:1",  # unreachable
        timeout_s=0.5,
    )
    fallback = AffectsEdge(
        source="CPIAUCSL", target="FEDFUNDS", hop_order=1,
        strength=0.55, confidence=0.72, sample_size=180,
        evidence_period="2021-06-12/2026-06-12",
    )
    result = aug.augment_affects(
        source=fallback.source, target=fallback.target,
        yaml_fallback=fallback,
    )
    assert result.degraded is True
    assert result.strength == fallback.strength  # unchanged
    assert result.confidence == fallback.confidence


def test_walker_tool_yaml_registers_via_lookup_capability():
    """The walker tool YAML must be discoverable; capability id ends in
    `.neo4j_macro_graph_walker`."""
    import yaml

    yaml_path = (
        pathlib.Path(__file__).parent.parent.parent
        / "registry" / "tool" / "vm105.neo4j_macro_graph_walker.yaml"
    )
    assert yaml_path.exists(), (
        f"Plan 87-03 must commit walker tool YAML at {yaml_path}"
    )
    data = yaml.safe_load(yaml_path.read_text())
    assert data["id"] == "vm105.neo4j_macro_graph_walker"
    assert data["type"] == "tool"
    assert data["status"] == "real"
    assert data["shipped"] == 87
    assert "vm107.macro_transmission_analyst" in data["allowed_agent_profiles"]
