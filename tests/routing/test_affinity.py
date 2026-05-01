"""
Affinity map tests — covers ROUTER-AFFINITY-01 + ROUTER-WEIGHTS-01.

test_yaml_loads_with_required_keys and test_mode_weights_sum pass immediately
(YAML skeleton ships with correct values). Other tests xfail until Plan 02
implements AffinityMap.lookup().

Per-task verification map commands (from VALIDATION.md):
    pytest tests/routing/test_affinity.py -x -q
    pytest tests/routing/test_affinity.py::test_mode_weights_sum -x -q
"""
import pytest
import yaml
from pathlib import Path

from core.routing.affinity import AffinityMap

# Path to the model_routing.yaml skeleton (relative to VM107 root)
YAML_PATH = Path(__file__).parents[2] / "conf" / "model_routing.yaml"


def test_yaml_loads_with_required_keys():
    """
    YAML parses without error and contains all required top-level keys.

    Passes immediately (Wave 0 skeleton ships with correct structure).
    """
    cfg = yaml.safe_load(YAML_PATH.read_text())
    assert cfg["version"] == "1.0"
    assert {"timezone", "peak_hours"} <= set(cfg["routing"])
    assert {"exploration", "exploitation", "stabilization"} == set(cfg["mode_weights"])


def test_mode_weights_sum():
    """
    All three mode_weight sets sum to exactly 1.0.

    Passes immediately (Wave 0 default values are mathematically correct).
    Validates: exploration (0.6+0.25+0.15=1.0), exploitation (0.4+0.4+0.2=1.0),
               stabilization (0.2+0.3+0.5=1.0).
    """
    cfg = yaml.safe_load(YAML_PATH.read_text())
    for mode, w in cfg["mode_weights"].items():
        total = w["quality"] + w["cost"] + w["latency"]
        assert abs(total - 1.0) < 1e-9, (
            f"{mode} mode_weights sum to {total}, expected 1.0. "
            f"Values: quality={w['quality']}, cost={w['cost']}, latency={w['latency']}"
        )


def test_lookup_agent_zero_analysis():
    """AffinityMap.lookup() returns correct chain for known agent_zero + analysis."""
    am = AffinityMap.from_yaml(str(YAML_PATH))
    chain = am.lookup("agent_zero", "analysis")
    assert "anthropic/claude-4-sonnet-20250514" in chain["primary"]
    assert chain["local"]   # never empty


def test_default_fallback_chain_lookup():
    """AffinityMap.lookup() returns correct chain for known (agent_id, task_type) pair."""
    am = AffinityMap.from_yaml(str(YAML_PATH))
    chain = am.lookup("agent_zero", "execution")
    assert "openai/gpt-4o" in chain["primary"]
    assert isinstance(chain["secondary"], list)
    assert isinstance(chain["local"], list)
    assert chain["local"]  # never empty


def test_unknown_agent_falls_back_to_default():
    """AffinityMap.lookup() uses affinity['default']['default'] for unknown agent_id."""
    am = AffinityMap.from_yaml(str(YAML_PATH))
    chain = am.lookup("future_agent_xyz", "any_task")
    assert "openai/gpt-4o" in chain["primary"]   # default.default


def test_unknown_task_type_falls_back_to_agent_default():
    """AffinityMap.lookup() uses affinity[agent_id]['default'] for unknown task_type."""
    am = AffinityMap.from_yaml(str(YAML_PATH))
    chain = am.lookup("agent_zero", "custom_research_unknown")
    assert "anthropic/claude-4-sonnet-20250514" in chain["primary"]   # agent_zero.default


def test_invalid_mode_weights_raises(tmp_path):
    """AffinityMap.from_yaml() raises ValueError when any mode_weights row sums != 1.0."""
    bad = tmp_path / "bad.yaml"
    bad.write_text("""
version: "1.0"
routing: {timezone: "UTC", peak_hours: []}
mode_weights:
  exploration: {quality: 0.5, cost: 0.5, latency: 0.5}
  exploitation: {quality: 0.4, cost: 0.4, latency: 0.2}
  stabilization: {quality: 0.2, cost: 0.3, latency: 0.5}
models: {}
affinity: {default: {default: {primary: ["x"], secondary: ["y"], local: ["z"]}}}
""")
    with pytest.raises(ValueError, match="mode_weights"):
        AffinityMap.from_yaml(str(bad))


def test_local_tier_always_present():
    """affinity[agent][task].local is never empty for any entry in the catalog."""
    am = AffinityMap.from_yaml(str(YAML_PATH))
    for agent_id, blk in am.affinity.items():
        for tt, chain in blk.items():
            assert chain["local"], f"affinity[{agent_id}][{tt}].local is empty"


def test_budget_caps_loaded():
    """budget_caps block is loaded from YAML and values match locked spec."""
    am = AffinityMap.from_yaml(str(YAML_PATH))
    assert am.budget_caps["agent_types"]["agent_zero"]["max_usd_per_day"] == 5.00
    assert am.budget_caps["agent_types"]["default"]["max_usd_per_day"] == 1.00
    assert am.budget_caps["system"]["max_usd_per_day"] == 50.00


def test_lookup_returns_dict_shape():
    """lookup() always returns {primary: list, secondary: list, local: list} shape."""
    am = AffinityMap.from_yaml(str(YAML_PATH))
    for agent_id in ("agent_zero", "unknown_agent"):
        for task_type in ("analysis", "unknown_task"):
            chain = am.lookup(agent_id, task_type)
            assert set(chain.keys()) == {"primary", "secondary", "local"}
            assert isinstance(chain["primary"], list)
            assert isinstance(chain["secondary"], list)
            assert isinstance(chain["local"], list)
            assert chain["local"]  # local is always non-empty
