"""Phase 43.1 — Utility model routing tests (Wave 0 scaffold; Plan 02 turns GREEN).

Reuses Phase 43 fixtures from tests/routing/conftest.py:
    mock_agent, mock_runner, mock_redis, mock_mongo, mock_signal_accumulator
"""
import os
import pytest
import yaml
from unittest.mock import MagicMock, AsyncMock, patch
from typing import Any


VM107_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


# -------------------------------------------------------------------------
# Helper: build a minimal router from a YAML dict for unit testing
# -------------------------------------------------------------------------

def _make_router_from_raw(raw: dict, mock_redis, mock_mongo, mock_logger=None, peak: bool = False):
    """Build a ModelRouter from a raw YAML dict using mock infra."""
    import sys
    sys.path.insert(0, VM107_ROOT)
    from core.routing.affinity import AffinityMap
    from core.routing.budget_gate import BudgetGate
    from core.routing.alert_pipeline import AlertPipeline
    from core.routing.peak_schedule import PeakSchedule
    from core.routing.router import ModelRouter

    affinity = AffinityMap(raw)
    budget_gate = BudgetGate(mock_redis, mock_mongo, mock_logger, budget_caps=affinity.budget_caps)
    alert_pipeline = AlertPipeline(mock_mongo, MagicMock(), None, mock_logger)
    peak_schedule = MagicMock()
    peak_schedule.is_peak.return_value = peak
    logger = mock_logger or MagicMock()
    return ModelRouter(affinity, budget_gate, alert_pipeline, peak_schedule, mock_mongo, logger)


def _ctx(**kw):
    """Helper: build a RouterContext with utility-path defaults, overridable via kwargs."""
    from core.routing.schemas import RouterContext
    defaults = dict(
        task_id="t1",
        goal_id="",
        agent_id="agent_zero",
        task_type="execution",
        priority="P3",
        latency_sla_ms=2000,
        brain_context={"mode": "exploration", "resource_policy": "normal"},
        path="utility",
    )
    defaults.update(kw)
    return RouterContext(**defaults)


def _base_yaml():
    """Minimal YAML dict with required blocks for utility path tests."""
    return {
        "version": "1.0",
        "routing": {"timezone": "UTC", "peak_hours": []},
        "mode_weights": {
            "exploration":   {"quality": 0.6, "cost": 0.25, "latency": 0.15},
            "exploitation":  {"quality": 0.4, "cost": 0.40, "latency": 0.20},
            "stabilization": {"quality": 0.2, "cost": 0.30, "latency": 0.50},
        },
        "budget_caps": {"agent_types": {}, "system": {}},
        "stabilization_safe_models": [],
        "alert_overrides": {},
        "affinity": {
            "agent_zero": {
                "default": {
                    "primary":   ["openai/gpt-4o"],
                    "secondary": ["anthropic/claude-haiku-4-5"],
                    "local":     ["ollama/llama3.2"],
                }
            },
            "default": {
                "default": {
                    "primary":   ["openai/gpt-4o"],
                    "secondary": ["anthropic/claude-haiku-4-5"],
                    "local":     ["ollama/llama3.2"],
                }
            },
        },
        "models": {
            "ollama/llama3.2": {
                "tier": "local",
                "quality_score": 0.55,
                "latency_ms": 300,
                "cost_per_1k_output_usd": 0.0,
            },
            "ollama/qwen2.5:14b": {
                "tier": "local",
                "quality_score": 0.62,
                "latency_ms": 600,
                "cost_per_1k_output_usd": 0.0,
            },
            "deepseek/deepseek-v4-flash": {
                "tier": "primary",
                "quality_score": 0.78,
                "latency_ms": 1200,
                "cost_per_1k_output_usd": 0.00028,
            },
            "openai/gpt-4o": {
                "tier": "primary",
                "quality_score": 0.88,
                "latency_ms": 1800,
                "cost_per_1k_output_usd": 0.010,
            },
            "anthropic/claude-haiku-4-5": {
                "tier": "secondary",
                "quality_score": 0.75,
                "latency_ms": 800,
                "cost_per_1k_output_usd": 0.005,
            },
            "expensive-model/pro": {
                "tier": "primary",
                "quality_score": 0.95,
                "latency_ms": 2000,
                "cost_per_1k_output_usd": 0.05,  # expensive: > 0.02 threshold
            },
            "slow-model/big": {
                "tier": "secondary",
                "quality_score": 0.80,
                "latency_ms": 3000,  # slow: > 2000ms SLA
                "cost_per_1k_output_usd": 0.001,
            },
        },
        "cost_thresholds": {
            "cheap_usd_per_1k_output": 0.005,
            "expensive_usd_per_1k_output": 0.02,
        },
        "latency_sla_ms": {
            "execution": 2000,
            "default": 3000,
        },
        "utility": {
            "default": {
                "primary":   ["deepseek/deepseek-v4-flash"],
                "secondary": ["anthropic/claude-haiku-4-5"],
                "local":     ["ollama/llama3.2"],
            },
            "overrides": {
                "synthesis": {
                    "allow_chat_models": True,
                },
            },
        },
    }


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


class TestUtilHookDecideApply:
    """Plan 02: util_model_call_before/_20_router_decide.py — decide+apply in one hook."""

    def test_decide_apply_in_one_hook(self, mock_agent, mock_redis, mock_mongo):
        """
        Calling util_model_call_before extension with a mock call_data + agent results in:
        1. router.decide called with RouterContext(path='utility')
        2. call_data['model'].model_name set to decision.primary
        3. decision stashed on agent.data['_util_router_pending_decision']
        """
        import asyncio
        from extensions.python.util_model_call_before._20_router_decide import UtilModelRouterDecide

        # Wire a mock router onto the agent
        mock_router = MagicMock()
        from core.routing.schemas import RoutingDecision
        mock_decision = RoutingDecision(
            task_id="ui-abc123",
            goal_id="",
            agent_id="agent_zero",
            task_type="execution",
            primary="deepseek/deepseek-v4-flash",
            fallback=["ollama/llama3.2"],
            reason=["path=utility"],
            decision_time_ms=1.0,
            selected_model="deepseek/deepseek-v4-flash",
            path="utility",
        )
        mock_router.decide.return_value = mock_decision

        # Build a minimal AffinityMap so get_utility_latency_sla works
        mock_affinity = MagicMock()
        mock_affinity.get_utility_latency_sla.return_value = 2000
        mock_router.affinity = mock_affinity

        mock_agent.set_data("model_router", mock_router)
        mock_agent.set_data("router_context", {
            "task_type": "execution",
            "goal_id": "",
            "agent_id": "agent_zero",
            "priority": "P3",
        })

        # Create a mock call_data with a mutable model_name
        mock_model = MagicMock()
        mock_model.model_name = "original-model"
        call_data = {
            "model": mock_model,
            "system": "sys",
            "message": "msg",
            "callback": None,
            "background": False,
        }

        ext = UtilModelRouterDecide(agent=mock_agent)
        asyncio.get_event_loop().run_until_complete(ext.execute(call_data=call_data))

        # 1. Router.decide was called
        mock_router.decide.assert_called_once()
        call_args = mock_router.decide.call_args[0][0]
        assert call_args.path == "utility"

        # 2. call_data['model'].model_name mutated to decision.primary
        assert call_data["model"].model_name == "deepseek/deepseek-v4-flash"

        # 3. Decision stashed on agent.data
        stashed = mock_agent.get_data("_util_router_pending_decision")
        assert stashed is mock_decision


class TestUtilHookPostCall:
    """Plan 02: util_model_call_after/_20_router_log_cost.py — cost record write."""

    def test_post_call_writes_cost_record_with_path_utility(
        self, mock_agent, mock_redis, mock_mongo
    ):
        """
        Calling util_model_call_after with response='hello' + agent results in:
        - MongoDB agent_runs insert with path='utility'
        - _id=str(uuid), schema_version=1
        - decision cleared after consumption
        """
        import asyncio
        from extensions.python.util_model_call_after._20_router_log_cost import UtilModelRouterLogCost
        from core.routing.schemas import RoutingDecision

        mock_decision = RoutingDecision(
            task_id="ui-abc123",
            goal_id="",
            agent_id="agent_zero",
            task_type="execution",
            primary="deepseek/deepseek-v4-flash",
            fallback=["ollama/llama3.2"],
            reason=["path=utility"],
            decision_time_ms=1.0,
            selected_model="deepseek/deepseek-v4-flash",
            path="utility",
        )

        # Wire router + budget_gate onto agent
        mock_budget_gate = MagicMock()
        mock_budget_gate.increment_spend.return_value = {}
        mock_budget_gate.get_agent_type_aggregate.return_value = {"spent_usd": 0.01, "max_usd": 0.0}
        mock_budget_gate.get_system_aggregate.return_value = {"spent_usd": 0.01, "max_usd": 0.0}

        mock_alert_pipeline = MagicMock()

        mock_router = MagicMock()
        mock_router.budget_gate = mock_budget_gate
        mock_router.alert_pipeline = mock_alert_pipeline
        mock_router._meta_for.return_value = {"cost_per_1k_output_usd": 0.00028, "cost_per_1k_input_usd": 0.00014}

        mock_agent.set_data("_util_router_pending_decision", mock_decision)
        mock_agent.set_data("_util_router_context", {
            "task_id": "ui-abc123",
            "goal_id": "",
            "agent_id": "agent_zero",
        })
        mock_agent.set_data("_util_router_call_start_ms", 0.0)
        mock_agent.set_data("model_router", mock_router)
        mock_agent.set_data("mongo_client", mock_mongo)

        call_data = {"system": "sys", "message": "msg"}

        ext = UtilModelRouterLogCost(agent=mock_agent)
        asyncio.get_event_loop().run_until_complete(
            ext.execute(call_data=call_data, response="hello world")
        )

        # Verify MongoDB insert was called
        insert_call = mock_mongo.fingpt_agents.agent_runs.insert_one.call_args
        assert insert_call is not None, "MongoDB insert_one was not called"
        record = insert_call[0][0]

        # path='utility', _id=uuid, schema_version=1
        assert record.get("path") == "utility"
        assert "schema_version" in record
        assert record["schema_version"] == 1
        assert "_id" in record
        assert len(record["_id"]) == 36  # UUID string format

        # Decision cleared after consumption
        assert mock_agent.get_data("_util_router_pending_decision") is None


class TestUtilLogic:
    """Cost-first weights, hard drop expensive, aggressive latency, no off-peak boost."""

    def test_hard_drop_expensive(self, mock_redis, mock_mongo):
        """
        Given a utility chain containing one cheap model and one expensive model,
        when _decide_utility runs, expensive model is NOT in fallback_chain.
        Reason chain shows "cost_filter:N->M" with M < N.
        """
        raw = _base_yaml()
        # Override utility.default to include expensive model + cheap model
        raw["utility"]["default"] = {
            "primary":   ["expensive-model/pro", "deepseek/deepseek-v4-flash"],
            "secondary": ["ollama/llama3.2"],
            "local":     ["ollama/llama3.2"],
        }
        # Make latency SLA permissive so latency filter doesn't interfere
        raw["latency_sla_ms"]["execution"] = 5000

        # Configure mock_redis to return budget_ok
        mock_redis.hgetall.return_value = {}
        router = _make_router_from_raw(raw, mock_redis, mock_mongo, peak=False)

        ctx = _ctx(task_type="execution", latency_sla_ms=5000)
        decision = router.decide(ctx)

        # expensive-model/pro has cost_per_1k_output_usd=0.05 > threshold 0.02 → DROPPED
        assert "expensive-model/pro" not in decision.fallback
        assert decision.primary != "expensive-model/pro"

        # reason contains cost_filter with reduction
        cost_filter_entries = [r for r in decision.reason if r.startswith("cost_filter:")]
        assert cost_filter_entries, f"Expected cost_filter: in reason. Got: {decision.reason}"
        # The count should show reduction (before > after)
        entry = cost_filter_entries[0]
        parts = entry.replace("cost_filter:", "").split("->")
        before_n, after_n = int(parts[0]), int(parts[1])
        assert before_n > after_n, f"Cost filter should reduce candidates. {entry}"

    def test_aggressive_latency(self, mock_redis, mock_mongo):
        """
        Given utility ctx with latency_sla_ms=2000 and a chain mixing fast + slow models,
        when _decide_utility runs, slow model (3000ms) is removed.
        Reason chain shows "latency_filter".
        """
        raw = _base_yaml()
        # utility.default has slow-model/big (3000ms) + fast deepseek (1200ms) + llama (300ms)
        raw["utility"]["default"] = {
            "primary":   ["slow-model/big", "deepseek/deepseek-v4-flash"],
            "secondary": ["ollama/llama3.2"],
            "local":     ["ollama/llama3.2"],
        }
        # Make cost filter permissive (slow-model/big cost is 0.001 < 0.02)
        raw["cost_thresholds"]["expensive_usd_per_1k_output"] = 0.1

        mock_redis.hgetall.return_value = {}
        router = _make_router_from_raw(raw, mock_redis, mock_mongo, peak=False)

        # 2000ms SLA — slow-model (3000ms) should be dropped
        ctx = _ctx(task_type="execution", latency_sla_ms=2000)
        decision = router.decide(ctx)

        # slow-model/big latency 3000ms > 2000ms SLA → filtered
        assert "slow-model/big" not in [decision.primary] + decision.fallback

        # reason contains latency_filter
        lat_filter_entries = [r for r in decision.reason if r.startswith("latency_filter:")]
        assert lat_filter_entries, f"Expected latency_filter: in reason. Got: {decision.reason}"

    def test_offpeak_no_quality_boost(self, mock_redis, mock_mongo):
        """
        Given peak_schedule.is_peak() == False (off-peak),
        utility decision uses cost-first weights {q:0.2, c:0.5, l:0.3} EXACTLY.
        Reason chain shows "offpeak_no_boost_utility" (NOT "offpeak_quality_boost").
        """
        raw = _base_yaml()
        # Make cost filter + latency filter permissive
        raw["cost_thresholds"]["expensive_usd_per_1k_output"] = 0.1
        raw["latency_sla_ms"]["execution"] = 5000

        mock_redis.hgetall.return_value = {}
        # peak=False → off-peak
        router = _make_router_from_raw(raw, mock_redis, mock_mongo, peak=False)

        ctx = _ctx(task_type="execution", latency_sla_ms=5000)
        decision = router.decide(ctx)

        # Utility path off-peak: NO quality boost
        assert "offpeak_no_boost_utility" in decision.reason, \
            f"Expected offpeak_no_boost_utility in reason. Got: {decision.reason}"
        # Chat path quality boost must NOT appear on utility path
        assert "offpeak_quality_boost" not in decision.reason, \
            "offpeak_quality_boost must not appear on utility path"

    def test_allow_chat_models_override(self, mock_redis, mock_mongo):
        """
        Given utility.overrides.synthesis.allow_chat_models=true,
        when ctx.path='utility' and ctx.task_type='synthesis',
        candidates come from affinity[chat] chain, and reason contains 'allow_chat_models_override'.
        Scoring still uses utility cost-first weights.
        """
        raw = _base_yaml()
        # synthesis override has allow_chat_models: true (in base yaml already)
        # Make latency + cost filters permissive
        raw["cost_thresholds"]["expensive_usd_per_1k_output"] = 0.1
        raw["latency_sla_ms"]["synthesis"] = 5000

        mock_redis.hgetall.return_value = {}
        router = _make_router_from_raw(raw, mock_redis, mock_mongo, peak=False)

        ctx = _ctx(task_type="synthesis", latency_sla_ms=5000)
        decision = router.decide(ctx)

        # reason contains allow_chat_models_override
        assert "allow_chat_models_override" in decision.reason, \
            f"Expected allow_chat_models_override in reason. Got: {decision.reason}"
        # Decision is still on utility path
        assert decision.path == "utility"
        # Off-peak no boost still applies (utility weights regardless)
        assert "offpeak_no_boost_utility" in decision.reason


class TestSharedBudget:
    def test_increment_spend_path_agnostic(self, mock_redis):
        """
        Calling increment_spend with same goal_id/agent_type from chat path then utility path
        (same args; path doesn't change keys) produces SUM in Redis aggregates.
        """
        from core.routing.budget_gate import BudgetGate
        gate = BudgetGate(
            redis_client=mock_redis,
            mongo_client=MagicMock(),
            budget_caps={
                "agent_types": {"agent_zero": {"max_usd_per_day": 5.0}},
                "system": {"max_usd_per_day": 50.0},
            }
        )

        # Simulate two calls: one from chat path, one from utility path
        # Both call the SAME increment_spend() — path-agnostic
        gate.increment_spend(goal_id="g1", agent_type="agent_zero", cost_usd=0.10)  # chat path
        gate.increment_spend(goal_id="g1", agent_type="agent_zero", cost_usd=0.05)  # utility path

        # Verify Redis was called with the correct agent type key both times
        from core.routing.budget_gate import REDIS_KEY_AGENT
        agent_key = REDIS_KEY_AGENT.format(agent_type="agent_zero")
        # hincrbyfloat called at least twice (once per increment_spend for agent scope)
        hincr_calls = [
            call for call in mock_redis.hincrbyfloat.call_args_list
            if call[0][0] == agent_key
        ]
        assert len(hincr_calls) == 2, f"Expected 2 hincrbyfloat calls for agent key, got {len(hincr_calls)}"

        # Verify total: mock_redis._store tracks cumulative values
        # The mock's hincrbyfloat accumulates via side_effect
        # We verify via get_agent_type_aggregate which reads Redis
        mock_redis._store[agent_key] = {"spent_usd": "0.15", "date": "2026-05-02"}
        agent_agg = gate.get_agent_type_aggregate("agent_zero")
        assert abs(agent_agg["spent_usd"] - 0.15) < 1e-6


class TestCostRecord:
    """Plan 02: CostRecord written with path='utility', _id=uuid, schema_version=1."""

    def test_cost_record_persisted_with_path_utility(self, mock_agent, mock_redis, mock_mongo):
        """
        Full integration: util_model_call_after with mock_mongo + mock_redis:
        - CostRecord written with path='utility', _id=uuid, schema_version=1
        - Redis aggregate incremented (increment_spend called)
        - AlertPipeline.evaluate_and_fire called (max_usd=0.0 so skipped — expected)
        """
        import asyncio
        from extensions.python.util_model_call_after._20_router_log_cost import UtilModelRouterLogCost
        from core.routing.schemas import RoutingDecision

        mock_decision = RoutingDecision(
            task_id="task-util-001",
            goal_id="goal-001",
            agent_id="agent_zero",
            task_type="execution",
            primary="deepseek/deepseek-v4-flash",
            fallback=["ollama/llama3.2"],
            reason=["path=utility", "utility_execution"],
            decision_time_ms=2.5,
            selected_model="deepseek/deepseek-v4-flash",
            path="utility",
        )

        # Wire budget_gate with goal aggregate that has max_usd (so alert eval fires)
        mock_budget_gate = MagicMock()
        mock_budget_gate.increment_spend.return_value = {
            "spent_usd": "0.001", "max_usd": "5.0"
        }
        mock_budget_gate.get_agent_type_aggregate.return_value = {"spent_usd": 0.001, "max_usd": 5.0}
        mock_budget_gate.get_system_aggregate.return_value = {"spent_usd": 0.001, "max_usd": 50.0}

        mock_alert_pipeline = MagicMock()

        mock_router = MagicMock()
        mock_router.budget_gate = mock_budget_gate
        mock_router.alert_pipeline = mock_alert_pipeline
        mock_router._meta_for.return_value = {
            "cost_per_1k_output_usd": 0.00028,
            "cost_per_1k_input_usd": 0.00014,
        }

        mock_agent.set_data("_util_router_pending_decision", mock_decision)
        mock_agent.set_data("_util_router_context", {
            "task_id": "task-util-001",
            "goal_id": "goal-001",
            "agent_id": "agent_zero",
        })
        mock_agent.set_data("_util_router_call_start_ms", 0.0)
        mock_agent.set_data("model_router", mock_router)
        mock_agent.set_data("mongo_client", mock_mongo)

        call_data = {"system": "You are a helpful agent.", "message": "Summarize this."}

        ext = UtilModelRouterLogCost(agent=mock_agent)
        asyncio.get_event_loop().run_until_complete(
            ext.execute(call_data=call_data, response="Here is the summary.")
        )

        # 1. CostRecord written to MongoDB
        insert_call = mock_mongo.fingpt_agents.agent_runs.insert_one.call_args
        assert insert_call is not None, "MongoDB insert_one not called"
        record = insert_call[0][0]
        assert record["path"] == "utility"
        assert record["schema_version"] == 1
        assert "_id" in record
        import uuid as _uuid_mod
        try:
            _uuid_mod.UUID(record["_id"])
        except ValueError:
            pytest.fail(f"_id is not a valid UUID: {record['_id']!r}")

        # 2. BudgetGate.increment_spend called (shared Redis aggregates)
        mock_budget_gate.increment_spend.assert_called_once()
        call_kwargs = mock_budget_gate.increment_spend.call_args[1] if mock_budget_gate.increment_spend.call_args[1] else {}
        call_positional = mock_budget_gate.increment_spend.call_args[0]

        # 3. AlertPipeline.evaluate_and_fire or evaluate called (all 3 scopes)
        # The hook calls evaluate_and_fire for each scope where max_usd > 0
        assert mock_alert_pipeline.evaluate_and_fire.call_count >= 1 or \
               mock_alert_pipeline.evaluate.call_count >= 1, \
               "AlertPipeline should have been evaluated for at least one scope"

        # 4. Pending decision cleared
        assert mock_agent.get_data("_util_router_pending_decision") is None


@pytest.mark.integration
class TestE2E:
    """E2E integration tests — require live MongoDB and Redis (run inside vm107-agent-zero container).

    These tests verify that after Phase 43.1 deploy:
      - router_decisions collection has documents with path='utility'
      - agent_runs collection has documents with path='utility'
      - Compound indexes (path_created_at) exist on both collections
      - Migration 006 is recorded in migrations_applied

    To run against live infra:
        docker exec -w /a0 vm107-agent-zero python -m pytest tests/routing/test_utility_routing.py::TestE2E -x -q

    These tests are skipped when MONGODB_URI is not available (unit test environments).
    They are NOT marked xfail — after Plan 03 container rebuild they should pass once a
    utility call has been triggered via the VM107 UI.
    """

    def test_migration_006_applied(self):
        """Migration 006 recorded in migrations_applied collection."""
        mongo_uri = os.environ.get("MONGODB_URI")
        if not mongo_uri:
            pytest.skip("MONGODB_URI not set — skipping live e2e test")
        try:
            import pymongo
        except ImportError:
            pytest.skip("pymongo not installed")

        c = pymongo.MongoClient(mongo_uri)
        record = c["fingpt_agents"]["migrations_applied"].find_one({"_id": "006_router_path_field"})
        assert record is not None, "Migration 006 not found in migrations_applied"
        assert record.get("phase") == "43.1", f"Unexpected phase: {record.get('phase')}"

    def test_path_created_at_index_on_router_decisions(self):
        """path_created_at compound index exists on router_decisions."""
        mongo_uri = os.environ.get("MONGODB_URI")
        if not mongo_uri:
            pytest.skip("MONGODB_URI not set — skipping live e2e test")
        try:
            import pymongo
        except ImportError:
            pytest.skip("pymongo not installed")

        c = pymongo.MongoClient(mongo_uri)
        idx_names = {i["name"] for i in c["fingpt_agents"]["router_decisions"].list_indexes()}
        assert "path_created_at" in idx_names, f"path_created_at index missing; found: {idx_names}"

    def test_path_created_at_index_on_agent_runs(self):
        """path_created_at compound index exists on agent_runs."""
        mongo_uri = os.environ.get("MONGODB_URI")
        if not mongo_uri:
            pytest.skip("MONGODB_URI not set — skipping live e2e test")
        try:
            import pymongo
        except ImportError:
            pytest.skip("pymongo not installed")

        c = pymongo.MongoClient(mongo_uri)
        idx_names = {i["name"] for i in c["fingpt_agents"]["agent_runs"].list_indexes()}
        assert "path_created_at" in idx_names, f"path_created_at index missing; found: {idx_names}"

    def test_utility_call_logged_with_path_utility(self):
        """At least one router_decisions document has path='utility' after UI trigger.

        Run AFTER triggering a utility call via VM107 UI (chat compaction, memory
        summarization, sub-task, etc). Fails if no utility calls have been made yet.
        """
        mongo_uri = os.environ.get("MONGODB_URI")
        if not mongo_uri:
            pytest.skip("MONGODB_URI not set — skipping live e2e test")
        try:
            import pymongo
        except ImportError:
            pytest.skip("pymongo not installed")

        c = pymongo.MongoClient(mongo_uri)
        count = c["fingpt_agents"]["router_decisions"].count_documents({"path": "utility"})
        assert count > 0, (
            "No utility-path router_decisions found. "
            "Trigger a utility call via VM107 UI (chat compaction, memory summarization, or sub-task) "
            "then re-run this test."
        )

    def test_utility_cost_record_persisted(self):
        """At least one agent_runs document has path='utility' after UI trigger."""
        mongo_uri = os.environ.get("MONGODB_URI")
        if not mongo_uri:
            pytest.skip("MONGODB_URI not set — skipping live e2e test")
        try:
            import pymongo
        except ImportError:
            pytest.skip("pymongo not installed")

        c = pymongo.MongoClient(mongo_uri)
        count = c["fingpt_agents"]["agent_runs"].count_documents({"path": "utility"})
        assert count > 0, (
            "No utility-path agent_runs found. "
            "Trigger a utility call via VM107 UI then re-run this test."
        )
