"""Phase 43.1 — Utility model routing tests (Wave 0 scaffold; Plan 02 turns GREEN).

Reuses Phase 43 fixtures from tests/routing/conftest.py:
    mock_agent, mock_runner, mock_redis, mock_mongo, mock_signal_accumulator
"""
import pytest
from typing import Any

# ----------- Tests that GO GREEN at Wave 0 (after Task 2 lands) -----------


class TestPathField:
    def test_router_context_path_default(self):
        from core.routing.schemas import RouterContext
        ctx = RouterContext(
            task_id="t1", goal_id="g1", agent_id="agent_zero", task_type="default",
            priority="P3", latency_sla_ms=3000, brain_context={},
        )
        assert ctx.path == "chat"

    def test_router_context_path_utility(self):
        from core.routing.schemas import RouterContext
        ctx = RouterContext(
            task_id="t1", goal_id="g1", agent_id="agent_zero", task_type="default",
            priority="P3", latency_sla_ms=3000, brain_context={}, path="utility",
        )
        assert ctx.path == "utility"

    def test_routing_decision_path(self):
        from core.routing.schemas import RoutingDecision
        d = RoutingDecision(
            task_id="t1", goal_id="g1", agent_id="agent_zero", task_type="default",
            primary="m1", fallback=["m1"], force_local=False,
            reason=["x"], decision_time_ms=0.5, selected_model="m1", path="utility",
        )
        assert d.path == "utility"

    def test_cost_record_path(self):
        from core.routing.schemas import CostRecord
        c = CostRecord(
            task_id="t1", goal_id="g1", agent_id="agent_zero",
            model="m1", tokens=30, cost_usd=0.001, latency_ms=100,
        )
        assert c.path == "chat"  # default backward-compat
        c2 = CostRecord(
            task_id="t1", goal_id="g1", agent_id="agent_zero",
            model="m1", tokens=30, cost_usd=0.001, latency_ms=100, path="utility",
        )
        assert c2.path == "utility"


class TestUtilConfig:
    def test_missing_utility_block_raises(self, tmp_path):
        import yaml
        from core.routing.affinity import AffinityMap
        cfg = {
            "version": "1.0",
            "affinity": {"default": {"default": {"primary": ["m"], "secondary": [], "local": ["m"]}}},
            "mode_weights": {"exploration": {"quality": 1.0, "cost": 0.0, "latency": 0.0}},
        }
        f = tmp_path / "no_utility.yaml"
        f.write_text(yaml.safe_dump(cfg))
        with pytest.raises(KeyError, match="utility"):
            AffinityMap.from_yaml(str(f))

    def test_utility_default_fallback(self, tmp_path):
        import yaml
        from core.routing.affinity import AffinityMap
        cfg = {
            "version": "1.0",
            "affinity": {"default": {"default": {"primary": ["chatm"], "secondary": [], "local": ["chatm"]}}},
            "mode_weights": {"exploration": {"quality": 1.0, "cost": 0.0, "latency": 0.0}},
            "utility": {
                "default": {"primary": ["utilm"], "secondary": [], "local": ["utilm"]},
                "overrides": {},
            },
        }
        f = tmp_path / "with_utility.yaml"
        f.write_text(yaml.safe_dump(cfg))
        am = AffinityMap.from_yaml(str(f))
        chain = am.utility_lookup("totally_unknown_task_type")
        assert chain["primary"] == ["utilm"]


class TestSchemaLoad:
    def test_cost_thresholds_loaded(self, tmp_path):
        import yaml
        from core.routing.affinity import AffinityMap
        cfg = {
            "version": "1.0",
            "affinity": {"default": {"default": {"primary": ["m"], "secondary": [], "local": ["m"]}}},
            "mode_weights": {"exploration": {"quality": 1.0, "cost": 0.0, "latency": 0.0}},
            "utility": {"default": {"primary": ["m"], "secondary": [], "local": ["m"]}},
            "cost_thresholds": {"cheap_usd_per_1k_output": 0.005, "expensive_usd_per_1k_output": 0.02},
            "latency_sla_ms": {"execution": 2000, "default": 3000},
        }
        f = tmp_path / "full.yaml"
        f.write_text(yaml.safe_dump(cfg))
        am = AffinityMap.from_yaml(str(f))
        assert am.cost_thresholds["cheap_usd_per_1k_output"] == 0.005
        assert am.cost_thresholds["expensive_usd_per_1k_output"] == 0.02

    def test_latency_sla_loaded(self, tmp_path):
        import yaml
        from core.routing.affinity import AffinityMap
        cfg = {
            "version": "1.0",
            "affinity": {"default": {"default": {"primary": ["m"], "secondary": [], "local": ["m"]}}},
            "mode_weights": {"exploration": {"quality": 1.0, "cost": 0.0, "latency": 0.0}},
            "utility": {"default": {"primary": ["m"], "secondary": [], "local": ["m"]}},
            "latency_sla_ms": {"execution": 2000, "default": 3000},
        }
        f = tmp_path / "lat.yaml"
        f.write_text(yaml.safe_dump(cfg))
        am = AffinityMap.from_yaml(str(f))
        assert am.get_utility_latency_sla("execution") == 2000
        assert am.get_utility_latency_sla("default") == 3000
        assert am.get_utility_latency_sla("anything_else") == 3000  # falls to 'default'


# ----------- Tests that STAY xfail until Plan 02 lands hooks/router branch -----------

@pytest.mark.xfail(reason="Plan 02 implements util_model_call_before/_20_router_decide.py")
class TestUtilHookDecideApply:
    def test_decide_apply_in_one_hook(self):
        from extensions.python.util_model_call_before._20_router_decide import UtilModelRouterDecide  # noqa
        assert False  # Plan 02


@pytest.mark.xfail(reason="Plan 02 implements util_model_call_after/_20_router_log_cost.py")
class TestUtilHookPostCall:
    def test_post_call_writes_cost_record_with_path_utility(self):
        from extensions.python.util_model_call_after._20_router_log_cost import UtilModelRouterLogCost  # noqa
        assert False  # Plan 02


@pytest.mark.xfail(reason="Plan 02 implements ModelRouter._decide_utility branch")
class TestUtilLogic:
    def test_hard_drop_expensive(self): assert False
    def test_aggressive_latency(self): assert False
    def test_offpeak_no_quality_boost(self): assert False
    def test_allow_chat_models_override(self): assert False


@pytest.mark.xfail(reason="Plan 02 wires shared budget call from utility hook")
class TestSharedBudget:
    def test_increment_spend_path_agnostic(self): assert False


@pytest.mark.xfail(reason="Plan 02 cost record write path='utility' end-to-end")
class TestCostRecord:
    def test_cost_record_persisted_with_path_utility(self): assert False


@pytest.mark.xfail(reason="Plan 03 e2e checkpoint after VM107 rebuild")
class TestE2E:
    def test_utility_call_logged_with_path_utility(self): assert False
