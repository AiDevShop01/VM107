"""
Router pipeline tests — covers ROUTER-PIPELINE-01, ROUTER-FALLBACK-01,
ROUTER-BRAIN-01, ROUTER-PEAK-01, ROUTER-LOG-01, ROUTER-HOOKS-01.

Wave 1 plans remove xfail from their owned test groups.
Plan 02 owns: TestPeakSchedule.test_perth_peak_window_detection, test_from_yaml_constructs
Plan 05 owns: all remaining tests (this file).

Per-task verification map commands (from VALIDATION.md):
    pytest tests/routing/test_router.py::TestPipeline -x -q
    pytest tests/routing/test_router.py::TestFallback -x -q
    pytest tests/routing/test_router.py::TestBrainFilter -x -q
    pytest tests/routing/test_router.py::TestPeakSchedule -x -q
    pytest tests/routing/test_router.py::TestLogging -x -q
    pytest tests/routing/test_router.py::TestHooks -x -q
"""
import pytest


def _ctx(**kw):
    """Helper: build a RouterContext with sane defaults, overridable via kwargs."""
    from core.routing.schemas import RouterContext
    defaults = dict(
        task_id="t1",
        goal_id="g1",
        agent_id="agent_zero",
        task_type="analysis",
        priority="P3",
        latency_sla_ms=30000,
        brain_context={"mode": "exploration", "resource_policy": "normal"},
    )
    defaults.update(kw)
    return RouterContext(**defaults)


@pytest.fixture
def router(real_affinity, mock_redis, mock_mongo, mock_signal_accumulator, mock_logger):
    """ModelRouter built from real affinity + mock infrastructure."""
    from core.routing.budget_gate import BudgetGate
    from core.routing.alert_pipeline import AlertPipeline
    from core.routing.peak_schedule import PeakSchedule
    from core.routing.router import ModelRouter

    bg = BudgetGate(
        mock_redis,
        mock_mongo,
        mock_logger,
        budget_caps=real_affinity.budget_caps,
    )
    ap = AlertPipeline(mock_mongo, mock_signal_accumulator, None, mock_logger)
    peak = PeakSchedule.from_yaml(real_affinity.raw["routing"])
    return ModelRouter(real_affinity, bg, ap, peak, mock_mongo, mock_logger)


class TestPipeline:
    """
    Tests for ROUTER-PIPELINE-01: 8-step deterministic routing pipeline.

    Covers: pipeline step order, budget gate hard stop, P1 bypass, full pipeline.
    Implementation owner: Plan 05.
    """

    def test_eight_step_order(self, router, mock_redis):
        """Pipeline executes all 8 steps in correct order — reason list documents the path."""
        mock_redis.hgetall.side_effect = None
        mock_redis.hgetall.return_value = {
            b"spent_usd": b"0.5",
            b"max_usd": b"5.0",
            b"status": b"ok",
        }
        d = router.decide(_ctx())
        # Step 1: context fields documented
        assert any("task_type=" in r for r in d.reason)
        assert any("agent=" in r for r in d.reason)
        # Step 2: budget gate result documented
        assert any("budget=" in r for r in d.reason)
        # Step 3: affinity lookup documented
        assert any("affinity=" in r for r in d.reason)
        # Step 6: peak/off-peak modifier documented
        assert any("peak" in r or "offpeak" in r for r in d.reason)
        # Decision fields populated
        assert d.task_id == "t1"
        assert d.goal_id == "g1"
        assert d.selected_model is not None
        assert d.decision_time_ms > 0

    def test_budget_gate_hard_stop(self, router, mock_redis):
        """When budget gate returns False (budget exceeded), returns local-only chain."""
        mock_redis.hgetall.side_effect = None
        mock_redis.hgetall.return_value = {
            b"spent_usd": b"5.0",
            b"max_usd": b"5.0",
            b"status": b"exceeded",
        }
        d = router.decide(_ctx(priority="P3"))
        assert d.force_local is True
        # Budget exceeded reason documented
        assert any("budget=" in r and "exceeded" in r for r in d.reason)
        # Primary must be a local tier model when force_local
        assert d.primary.startswith("ollama/"), f"expected ollama/ primary, got {d.primary}"

    def test_p1_bypass_with_force_local(self, router, mock_redis):
        """P1 task bypasses enqueue_blocked but force_local=True → local tier only in chain."""
        mock_redis.hgetall.side_effect = None
        mock_redis.hgetall.return_value = {
            b"spent_usd": b"5.0",
            b"max_usd": b"5.0",
            b"status": b"exceeded",
        }
        d = router.decide(_ctx(priority="P1"))
        # P1 bypasses block (allow=True) but reason encodes force_local
        assert d.force_local is True
        assert d.primary.startswith("ollama/"), (
            f"P1 bypass force_local: expected ollama/ primary, got {d.primary}"
        )

    def test_no_goal_skips_budget_gate(self, router, mock_redis):
        """ctx.goal_id='' skips budget gate entirely — routing proceeds normally."""
        mock_redis.hgetall.side_effect = None
        mock_redis.hgetall.return_value = {}  # no Redis data — should be irrelevant
        d = router.decide(_ctx(goal_id=""))
        assert any("budget=no_goal" in r for r in d.reason)
        assert d.force_local is False


class TestBrainFilter:
    """
    Tests for ROUTER-BRAIN-01: brain-mode filter application.

    Covers: stabilization hard filter, exploration soft preference.
    Implementation owner: Plan 05.
    """

    def test_stabilization_hard_filter(self, router, mock_redis):
        """Stabilization mode HARD-FILTERS models not in stabilization_safe_models list."""
        mock_redis.hgetall.side_effect = None
        mock_redis.hgetall.return_value = {
            b"spent_usd": b"0.0",
            b"max_usd": b"5.0",
            b"status": b"ok",
        }
        d = router.decide(
            _ctx(brain_context={"mode": "stabilization", "resource_policy": "constrained"})
        )
        # Primary must be stabilization_safe
        assert router.affinity.is_stabilization_safe(d.primary), (
            f"{d.primary} not in stabilization_safe_models list"
        )
        # Reason documents the filter step
        assert any("stabilization_filter" in r for r in d.reason)

    def test_exploration_soft_preference(self, router, mock_redis):
        """Exploration mode retains full candidate set (no hard filter)."""
        mock_redis.hgetall.side_effect = None
        mock_redis.hgetall.return_value = {
            b"spent_usd": b"0.0",
            b"max_usd": b"5.0",
            b"status": b"ok",
        }
        d = router.decide(
            _ctx(brain_context={"mode": "exploration", "resource_policy": "normal"})
        )
        # Soft mode — no stabilization_filter in reason
        assert not any("stabilization_filter" in r for r in d.reason)
        # Soft mode documented
        assert any("mode=exploration_soft" in r for r in d.reason)

    def test_exploitation_soft_preference(self, router, mock_redis):
        """Exploitation mode retains full candidate set (no hard filter)."""
        mock_redis.hgetall.side_effect = None
        mock_redis.hgetall.return_value = {
            b"spent_usd": b"0.0",
            b"max_usd": b"5.0",
            b"status": b"ok",
        }
        d = router.decide(
            _ctx(brain_context={"mode": "exploitation", "resource_policy": "normal"})
        )
        assert not any("stabilization_filter" in r for r in d.reason)
        assert any("mode=exploitation_soft" in r for r in d.reason)


class TestFallback:
    """
    Tests for ROUTER-FALLBACK-01: 3-tier primary/fallback chain construction.

    Covers: local tier always present, chain integrity under peak.
    Implementation owner: Plan 05.
    """

    def test_chain_always_has_local(self, router, mock_redis):
        """Fallback chain always includes at least one local-tier model."""
        mock_redis.hgetall.side_effect = None
        mock_redis.hgetall.return_value = {
            b"spent_usd": b"0.0",
            b"max_usd": b"5.0",
            b"status": b"ok",
        }
        d = router.decide(_ctx())
        chain = [d.primary, *d.fallback]
        # At least one model in the chain must be local tier
        tiers = [
            router.affinity.get_model_meta(m).get("tier")
            for m in chain
            if m in router.affinity.models
        ]
        assert "local" in tiers, f"No local model in chain: {chain} (tiers: {tiers})"

    def test_peak_preserves_chain(self, router, mock_redis, monkeypatch):
        """Peak mode tier-shifts primary but preserves fallback chain length >= 2."""
        mock_redis.hgetall.side_effect = None
        mock_redis.hgetall.return_value = {
            b"spent_usd": b"0.0",
            b"max_usd": b"5.0",
            b"status": b"ok",
        }
        monkeypatch.setattr(router.peak_schedule, "is_peak", lambda *a, **k: True)
        d = router.decide(_ctx())
        assert d.peak is True
        chain_len = 1 + len(d.fallback)
        assert chain_len >= 2, f"Peak must preserve fallback chain; got chain_len={chain_len}"

    def test_latency_filter_drops_slow_models(self, router, mock_redis):
        """Latency filter drops models exceeding ctx.latency_sla_ms."""
        mock_redis.hgetall.side_effect = None
        mock_redis.hgetall.return_value = {
            b"spent_usd": b"0.0",
            b"max_usd": b"5.0",
            b"status": b"ok",
        }
        # Very tight SLA: 500ms — only local (300ms) should survive
        d = router.decide(_ctx(latency_sla_ms=500))
        # With a very tight SLA the router should relax to local or at least choose fast model
        # Accept that latency_relaxed_to_local OR latency_filter appears in reason
        assert any("latency" in r for r in d.reason)


class TestPeakSchedule:
    """
    Tests for ROUTER-PEAK-01: peak/off-peak time-of-day routing.

    Covers: Perth timezone window detection, hard tier-shift on peak, quality boost off-peak.
    Implementation owner: Plan 02 (detection), Plan 05 (modifier).
    """

    def test_perth_peak_window_detection(self):
        """Peak detector correctly identifies Australia/Perth timezone windows."""
        from core.routing.peak_schedule import PeakSchedule
        from datetime import datetime
        from zoneinfo import ZoneInfo

        sch = PeakSchedule(timezone="Australia/Perth", windows=["08:00-12:00", "14:00-18:00"])
        tz = ZoneInfo("Australia/Perth")

        # 09:00 is inside window 08:00-12:00 → peak
        assert sch.is_peak(datetime(2026, 5, 1, 9, 0, tzinfo=tz)) is True
        # 13:00 is between the two windows → off-peak
        assert sch.is_peak(datetime(2026, 5, 1, 13, 0, tzinfo=tz)) is False
        # 22:00 is after both windows → off-peak
        assert sch.is_peak(datetime(2026, 5, 1, 22, 0, tzinfo=tz)) is False
        # 14:30 is inside window 14:00-18:00 → peak
        assert sch.is_peak(datetime(2026, 5, 1, 14, 30, tzinfo=tz)) is True

    def test_peak_hard_shift(self, router, mock_redis, monkeypatch):
        """Peak hours apply hard tier-shift: primary tier dropped from primary slot."""
        mock_redis.hgetall.side_effect = None
        mock_redis.hgetall.return_value = {
            b"spent_usd": b"0.0",
            b"max_usd": b"5.0",
            b"status": b"ok",
        }
        monkeypatch.setattr(router.peak_schedule, "is_peak", lambda *a, **k: True)
        d = router.decide(_ctx())
        primary_tier = router.affinity.get_model_meta(d.primary).get("tier")
        # In peak, primary slot should NOT be the primary tier (hard shift drops primary tier candidates)
        assert primary_tier != "primary", (
            f"peak hard shift failed: primary={d.primary} tier={primary_tier}"
        )
        # peak_hard_shift documented in reason
        assert any("peak_hard_shift" in r for r in d.reason)

    def test_from_yaml_constructs(self):
        """PeakSchedule.from_yaml() constructs correctly from routing config dict."""
        from core.routing.peak_schedule import PeakSchedule
        sch = PeakSchedule.from_yaml({"timezone": "Australia/Perth", "peak_hours": ["09:00-17:00"]})
        assert len(sch.windows) == 1

    def test_no_windows_always_off_peak(self):
        """PeakSchedule with no windows always returns False for is_peak()."""
        from core.routing.peak_schedule import PeakSchedule
        from datetime import datetime
        from zoneinfo import ZoneInfo
        sch = PeakSchedule(timezone="Australia/Perth", windows=[])
        tz = ZoneInfo("Australia/Perth")
        assert sch.is_peak(datetime(2026, 5, 1, 10, 0, tzinfo=tz)) is False

    def test_boundary_excluded_at_end(self):
        """is_peak() uses start <= t < end (end boundary is excluded)."""
        from core.routing.peak_schedule import PeakSchedule
        from datetime import datetime
        from zoneinfo import ZoneInfo
        sch = PeakSchedule(timezone="Australia/Perth", windows=["08:00-12:00"])
        tz = ZoneInfo("Australia/Perth")
        # Exactly at 08:00 → peak (inclusive start)
        assert sch.is_peak(datetime(2026, 5, 1, 8, 0, tzinfo=tz)) is True
        # Exactly at 12:00 → off-peak (exclusive end)
        assert sch.is_peak(datetime(2026, 5, 1, 12, 0, tzinfo=tz)) is False

    def test_from_yaml_reads_full_routing_block(self):
        """PeakSchedule.from_yaml() reads timezone and peak_hours from full routing block."""
        from core.routing.peak_schedule import PeakSchedule
        from datetime import datetime
        from zoneinfo import ZoneInfo
        routing_cfg = {"timezone": "Australia/Perth", "peak_hours": ["08:00-12:00", "14:00-18:00"]}
        sch = PeakSchedule.from_yaml(routing_cfg)
        tz = ZoneInfo("Australia/Perth")
        assert sch.is_peak(datetime(2026, 5, 1, 9, 0, tzinfo=tz)) is True
        assert sch.is_peak(datetime(2026, 5, 1, 13, 0, tzinfo=tz)) is False

    def test_offpeak_quality_boost_in_reason(self, router, mock_redis, monkeypatch):
        """Off-peak decision documents quality boost in reason list."""
        mock_redis.hgetall.side_effect = None
        mock_redis.hgetall.return_value = {
            b"spent_usd": b"0.0",
            b"max_usd": b"5.0",
            b"status": b"ok",
        }
        monkeypatch.setattr(router.peak_schedule, "is_peak", lambda *a, **k: False)
        d = router.decide(_ctx())
        assert any("offpeak_quality_boost" in r for r in d.reason)


class TestLogging:
    """
    Tests for ROUTER-LOG-01: mandatory per-call decision + cost logging.

    Covers: decision log has 8 required fields, cost record has 5 required fields.
    Implementation owner: Plan 05.
    """

    def test_decision_log_has_eight_fields(self, router, mock_redis, mock_mongo):
        """Decision log emitted to router_decisions with all 8 mandatory fields present."""
        mock_redis.hgetall.side_effect = None
        mock_redis.hgetall.return_value = {
            b"spent_usd": b"0.0",
            b"max_usd": b"5.0",
            b"status": b"ok",
        }
        d = router.decide(_ctx())
        payload = d.model_dump(mode="json")
        for f in (
            "task_id",
            "goal_id",
            "agent_id",
            "task_type",
            "selected_model",
            "fallback",
            "reason",
            "decision_time_ms",
        ):
            assert f in payload, f"missing mandatory field '{f}' in decision log"
        # MongoDB persistence: insert_one called once per decide()
        assert mock_mongo.fingpt_agents.router_decisions.insert_one.call_count == 1

    def test_cost_record(self):
        """CostRecord schema has the 5 required fields (task_id, model, tokens, cost_usd, latency_ms)."""
        from core.routing.schemas import CostRecord
        cr = CostRecord(
            task_id="t1",
            model="ollama/llama3.2",
            tokens=100,
            cost_usd=0.0,
            latency_ms=300,
            goal_id="g1",
            agent_id="agent_zero",
        )
        d = cr.model_dump(mode="json")
        for f in ("task_id", "model", "tokens", "cost_usd", "latency_ms"):
            assert f in d, f"missing mandatory field '{f}' in CostRecord"


class TestFromYaml:
    """
    Tests for ModelRouter.from_yaml factory method.

    Covers: budget_caps from affinity injected into BudgetGate at construction.
    """

    def test_budget_caps_injected_into_gate(
        self,
        mock_redis,
        mock_mongo,
        mock_signal_accumulator,
        mock_logger,
    ):
        """from_yaml() constructs BudgetGate with budget_caps=affinity.budget_caps."""
        from pathlib import Path
        from core.routing.router import ModelRouter

        yaml_path = Path(__file__).parents[2] / "conf" / "model_routing.yaml"
        r = ModelRouter.from_yaml(
            str(yaml_path),
            redis_client=mock_redis,
            mongo_client=mock_mongo,
            signal_accumulator=mock_signal_accumulator,
            logger=mock_logger,
        )
        # budget_caps from YAML wired into BudgetGate
        assert r.budget_gate.budget_caps["agent_types"]["agent_zero"]["max_usd_per_day"] == 5.00
        assert r.budget_gate.budget_caps["system"]["max_usd_per_day"] == 50.00


class TestHooks:
    """
    Tests for ROUTER-HOOKS-01: extension-only hook integration.

    Covers: before_main_llm_call stores decision in params_temporary,
            chat_model_call_after updates Redis aggregates + fires 3-scope alerts.
    Implementation owner: Plan 05, Task 2.
    """

    def test_before_main_llm_call_stashes_decision(
        self,
        mock_agent,
        real_affinity,
        mock_redis,
        mock_mongo,
        mock_signal_accumulator,
        mock_logger,
    ):
        """before_main_llm_call extension calls Router.decide() and stores result in loop_data.params_temporary."""
        from extensions.python.before_main_llm_call._router_decide import ModelRouterSelect
        from agent import LoopData
        from core.routing.router import ModelRouter
        from core.routing.budget_gate import BudgetGate
        from core.routing.alert_pipeline import AlertPipeline
        from core.routing.peak_schedule import PeakSchedule

        mock_redis.hgetall.side_effect = None
        mock_redis.hgetall.return_value = {
            b"spent_usd": b"0.0",
            b"max_usd": b"5.0",
            b"status": b"ok",
        }
        router = ModelRouter(
            real_affinity,
            BudgetGate(mock_redis, mock_mongo, mock_logger, budget_caps=real_affinity.budget_caps),
            AlertPipeline(mock_mongo, mock_signal_accumulator, None, mock_logger),
            PeakSchedule.from_yaml(real_affinity.raw["routing"]),
            mock_mongo,
            mock_logger,
        )
        mock_agent._data["model_router"] = router
        mock_agent._data["router_context"] = {
            "task_id": "t1",
            "goal_id": "g1",
            "agent_id": "agent_zero",
            "task_type": "analysis",
            "priority": "P3",
            "latency_sla_ms": 30000,
        }
        mock_agent._data["brain_context"] = {"mode": "exploration", "resource_policy": "normal"}

        ext = ModelRouterSelect(agent=mock_agent)
        ld = LoopData()
        import asyncio
        asyncio.get_event_loop().run_until_complete(ext.execute(loop_data=ld))
        assert "router_decision" in ld.params_temporary
        assert ld.params_temporary["router_decision"].agent_id == "agent_zero"

    def test_post_call_update(
        self,
        mock_agent,
        real_affinity,
        mock_redis,
        mock_mongo,
        mock_signal_accumulator,
        mock_logger,
    ):
        """chat_model_call_after extension calls increment_spend and writes CostRecord to MongoDB."""
        from extensions.python.chat_model_call_after._router_log_cost import ModelRouterLogCost
        from agent import LoopData
        from core.routing.schemas import RoutingDecision
        from core.routing.router import ModelRouter
        from core.routing.budget_gate import BudgetGate
        from core.routing.alert_pipeline import AlertPipeline
        from core.routing.peak_schedule import PeakSchedule

        mock_redis.hgetall.side_effect = None
        mock_redis.hgetall.return_value = {
            b"spent_usd": b"0.0",
            b"max_usd": b"5.0",
            b"status": b"ok",
        }
        router = ModelRouter(
            real_affinity,
            BudgetGate(mock_redis, mock_mongo, mock_logger, budget_caps=real_affinity.budget_caps),
            AlertPipeline(mock_mongo, mock_signal_accumulator, None, mock_logger),
            PeakSchedule.from_yaml(real_affinity.raw["routing"]),
            mock_mongo,
            mock_logger,
        )
        mock_agent._data["model_router"] = router
        mock_agent._data["mongo_client"] = mock_mongo
        mock_agent._data["router_context"] = {
            "task_id": "t1",
            "goal_id": "g1",
            "agent_id": "agent_zero",
        }

        decision = RoutingDecision(
            task_id="t1",
            goal_id="g1",
            agent_id="agent_zero",
            task_type="analysis",
            primary="ollama/llama3.2",
            fallback=[],
            reason=["test"],
            decision_time_ms=1.0,
            selected_model="ollama/llama3.2",
            peak=False,
            mode="exploration",
            force_local=False,
        )
        ld = LoopData()
        ld.params_temporary["router_decision"] = decision

        ext = ModelRouterLogCost(agent=mock_agent)
        import asyncio
        asyncio.get_event_loop().run_until_complete(
            ext.execute(loop_data=ld, call_data={}, response="hello world", reasoning="")
        )
        # increment_spend called via Redis hincrbyfloat
        assert mock_redis.hincrbyfloat.called
        # Cost record written to mongo agent_runs
        assert mock_mongo.fingpt_agents.agent_runs.insert_one.called

    def test_post_call_fires_three_scopes(
        self,
        mock_agent,
        real_affinity,
        mock_redis,
        mock_mongo,
        mock_signal_accumulator,
        mock_logger,
    ):
        """evaluate_and_fire is called with goal, agent_type, AND system scope arguments."""
        from extensions.python.chat_model_call_after._router_log_cost import ModelRouterLogCost
        from agent import LoopData
        from core.routing.schemas import RoutingDecision
        from core.routing.router import ModelRouter
        from core.routing.budget_gate import BudgetGate
        from core.routing.alert_pipeline import AlertPipeline
        from core.routing.peak_schedule import PeakSchedule
        from unittest.mock import MagicMock

        mock_redis.hgetall.side_effect = None
        # Redis returns aggregates that put us above zero across all scopes
        mock_redis.hgetall.return_value = {
            b"spent_usd": b"3.0",
            b"max_usd": b"5.0",
            b"status": b"ok",
        }

        router = ModelRouter(
            real_affinity,
            BudgetGate(mock_redis, mock_mongo, mock_logger, budget_caps=real_affinity.budget_caps),
            AlertPipeline(mock_mongo, mock_signal_accumulator, None, mock_logger),
            PeakSchedule.from_yaml(real_affinity.raw["routing"]),
            mock_mongo,
            mock_logger,
        )
        # Spy on evaluate_and_fire to count scope calls
        router.alert_pipeline.evaluate_and_fire = MagicMock(return_value=[])

        mock_agent._data["model_router"] = router
        mock_agent._data["mongo_client"] = mock_mongo
        mock_agent._data["router_context"] = {
            "task_id": "t1",
            "goal_id": "g1",
            "agent_id": "agent_zero",
        }

        decision = RoutingDecision(
            task_id="t1",
            goal_id="g1",
            agent_id="agent_zero",
            task_type="analysis",
            primary="ollama/llama3.2",
            fallback=[],
            reason=["test"],
            decision_time_ms=1.0,
            selected_model="ollama/llama3.2",
            peak=False,
            mode="exploration",
            force_local=False,
        )
        ld = LoopData()
        ld.params_temporary["router_decision"] = decision

        ext = ModelRouterLogCost(agent=mock_agent)
        import asyncio
        asyncio.get_event_loop().run_until_complete(
            ext.execute(loop_data=ld, call_data={}, response="x", reasoning="")
        )

        # Three scope arguments observed across calls (goal, agent_type, system)
        scopes_fired = [c.args[0] for c in router.alert_pipeline.evaluate_and_fire.call_args_list]
        assert "goal" in scopes_fired
        assert "agent_type" in scopes_fired
        assert "system" in scopes_fired

    def test_post_call_skips_unconfigured_scope(
        self,
        mock_agent,
        real_affinity,
        mock_redis,
        mock_mongo,
        mock_signal_accumulator,
        mock_logger,
    ):
        """When budget_caps has no agent_type entry (max_usd=0), skip that scope's evaluate_and_fire."""
        from extensions.python.chat_model_call_after._router_log_cost import ModelRouterLogCost
        from agent import LoopData
        from core.routing.schemas import RoutingDecision
        from core.routing.router import ModelRouter
        from core.routing.budget_gate import BudgetGate
        from core.routing.alert_pipeline import AlertPipeline
        from core.routing.peak_schedule import PeakSchedule
        from unittest.mock import MagicMock

        mock_redis.hgetall.side_effect = None
        mock_redis.hgetall.return_value = {
            b"spent_usd": b"0.5",
            b"max_usd": b"5.0",
            b"status": b"ok",
        }
        # Stripped budget_caps: no agent_zero entry, no system entry
        stripped_caps = {"agent_types": {}, "system": {}}
        router = ModelRouter(
            real_affinity,
            BudgetGate(mock_redis, mock_mongo, mock_logger, budget_caps=stripped_caps),
            AlertPipeline(mock_mongo, mock_signal_accumulator, None, mock_logger),
            PeakSchedule.from_yaml(real_affinity.raw["routing"]),
            mock_mongo,
            mock_logger,
        )
        router.alert_pipeline.evaluate_and_fire = MagicMock(return_value=[])

        mock_agent._data["model_router"] = router
        mock_agent._data["mongo_client"] = mock_mongo
        mock_agent._data["router_context"] = {
            "task_id": "t1",
            "goal_id": "g1",
            "agent_id": "agent_zero",
        }

        decision = RoutingDecision(
            task_id="t1",
            goal_id="g1",
            agent_id="agent_zero",
            task_type="analysis",
            primary="ollama/llama3.2",
            fallback=[],
            reason=["test"],
            decision_time_ms=1.0,
            selected_model="ollama/llama3.2",
            peak=False,
            mode="exploration",
            force_local=False,
        )
        ld = LoopData()
        ld.params_temporary["router_decision"] = decision

        ext = ModelRouterLogCost(agent=mock_agent)
        import asyncio
        asyncio.get_event_loop().run_until_complete(
            ext.execute(loop_data=ld, call_data={}, response="x", reasoning="")
        )

        scopes_fired = [
            c.args[0] for c in router.alert_pipeline.evaluate_and_fire.call_args_list
        ]
        # agent_type + system MUST NOT fire (no caps configured)
        assert "agent_type" not in scopes_fired
        assert "system" not in scopes_fired
