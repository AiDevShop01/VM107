"""Pre-Neo4j audit — YAML structure + edge counts.

Reviewer can run this without spinning up testcontainers. Confirms the Wave 1
seed file at vm105/seeds/macro_graph_seed.yaml has the LOCK-1 shape
(12 indicators, >=60 AFFECTS, >=30 DRIVES) before any live load.

Per project lock — no os.getenv("X", "default") patterns; no hardcoded URLs.
"""
import pathlib

import pytest
import yaml

pytestmark = pytest.mark.phase_87

SEED_YAML = (
    pathlib.Path(__file__).parent.parent.parent.parent
    / "vm105" / "seeds" / "macro_graph_seed.yaml"
)

EXPECTED_IDS = {
    "CPIAUCSL", "PPIACO", "PAYEMS", "UNRATE", "FEDFUNDS", "GDP",
    "RSAFS", "ECBDFR", "BOJDFR", "NAPMPMI", "NAPM", "DGS10",
}


def test_yaml_loads():
    assert SEED_YAML.exists(), (
        f"Plan 87-03 must commit vm105/seeds/macro_graph_seed.yaml at {SEED_YAML}"
    )
    yaml.safe_load(SEED_YAML.read_text())


def test_12_indicators_present():
    data = yaml.safe_load(SEED_YAML.read_text())
    ids = {i["id"] for i in data["indicators"]}
    assert ids == EXPECTED_IDS, f"missing or extra ids: {ids ^ EXPECTED_IDS}"


def test_at_least_60_affects_edges():
    data = yaml.safe_load(SEED_YAML.read_text())
    total = sum(len(i.get("affects_chain", [])) for i in data["indicators"])
    assert total >= 60, f"REQ-87-1 needs >=60 AFFECTS edges, YAML has {total}"


def test_at_least_30_drives_edges():
    data = yaml.safe_load(SEED_YAML.read_text())
    total = sum(len(i.get("drives", [])) for i in data["indicators"])
    assert total >= 30, f"REQ-87-1 needs >=30 DRIVES edges, YAML has {total}"


def test_every_affects_edge_has_all_four_fallback_fields():
    data = yaml.safe_load(SEED_YAML.read_text())
    required = {"strength", "confidence", "sample_size", "evidence_period"}
    for ind in data["indicators"]:
        for edge in ind.get("affects_chain", []):
            missing = required - set(edge.keys())
            assert not missing, (
                f"{ind['id']}->{edge.get('target')} missing fallback fields: {missing}"
            )


def test_every_drives_edge_has_direction_and_fallbacks():
    data = yaml.safe_load(SEED_YAML.read_text())
    valid_directions = {"positive", "negative", "mixed", "neutral"}
    for ind in data["indicators"]:
        for edge in ind.get("drives", []):
            assert edge.get("direction") in valid_directions, (
                f"{ind['id']}->{edge.get('asset')} bad direction "
                f"{edge.get('direction')!r}"
            )
            for prop in ["strength", "confidence", "sample_size", "evidence_period"]:
                assert prop in edge, (
                    f"{ind['id']}->{edge.get('asset')} missing {prop}"
                )
