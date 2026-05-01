"""
Budget gate tests — covers ROUTER-BUDGET-01 + ROUTER-BREACH-01.

Per-task verification map commands (from VALIDATION.md):
    pytest tests/routing/test_budget_gate.py -x -q
    pytest tests/routing/test_budget_gate.py::TestBreach -x -q
    pytest tests/routing/test_budget_gate.py::TestBreach::test_p1_bypass -x -q
"""
import pytest
from core.routing.budget_gate import BudgetGate, REDIS_KEY_GOAL


class TestBudgetGate:
    """
    Tests for ROUTER-BUDGET-01: per-goal budget gate at routing time.

    Covers: Redis aggregate read, MongoDB cache-miss fallback, unconstrained goals.
    Implementation owner: Plan 03.
    """

    def test_redis_aggregate_read(self, mock_redis, mock_mongo, mock_logger):
        """BudgetGate.check() reads from router:budget:goal:{goal_id} HSET key in Redis."""
        mock_redis._store[REDIS_KEY_GOAL.format(goal_id="g1")] = {
            b"spent_usd": b"0.50", b"max_usd": b"5.00", b"status": b"ok"
        }
        # Patch hgetall to return the stored dict for this key
        mock_redis.hgetall.side_effect = lambda k: mock_redis._store.get(k, {})
        gate = BudgetGate(mock_redis, mock_mongo, mock_logger)
        allow, reason = gate.check("g1", "P3")
        assert allow is True
        assert reason == "budget_ok"

    def test_cache_miss_reads_mongo_once(self, mock_redis, mock_mongo, mock_logger):
        """On Redis cache miss, BudgetGate queries MongoDB once to initialize Redis key."""
        mock_redis._store = {}
        # side_effect already returns {} from empty _store — no override needed
        mock_mongo.fingpt_agents.agent_goals.find_one.return_value = {
            "goal_id": "g2", "budget_max_cost_usd": 10.0, "budget_spent_today": 1.5, "budget_status": "ok"
        }
        gate = BudgetGate(mock_redis, mock_mongo, mock_logger)
        allow, reason = gate.check("g2", "P3")
        assert allow is True
        assert mock_mongo.fingpt_agents.agent_goals.find_one.call_count == 1

    def test_no_budget_set_allows(self, mock_redis, mock_mongo, mock_logger):
        """Goals without budget_max_cost_usd set are allowed (no constraint = no block)."""
        # side_effect returns {} from empty _store — cache miss path triggers
        mock_mongo.fingpt_agents.agent_goals.find_one.return_value = {
            "goal_id": "g3", "budget_max_cost_usd": None
        }
        gate = BudgetGate(mock_redis, mock_mongo, mock_logger)
        allow, reason = gate.check("g3", "P3")
        assert allow is True
        assert reason == "no_budget_set"

    def test_unknown_goal_fails_open(self, mock_redis, mock_mongo, mock_logger):
        """Goals with no record in Mongo fail open (unknown goal = unconstrained)."""
        # side_effect returns {} from empty _store — cache miss path triggers
        mock_mongo.fingpt_agents.agent_goals.find_one.return_value = None
        gate = BudgetGate(mock_redis, mock_mongo, mock_logger)
        allow, reason = gate.check("ghost", "P3")
        assert allow is True
        assert reason == "unknown_goal"

    def test_redis_unavailable_fails_open(self, mock_redis, mock_mongo, mock_logger):
        """Redis failure fails open — agent must not be blocked by infrastructure failures."""
        mock_redis.hgetall.side_effect = ConnectionError("redis down")
        gate = BudgetGate(mock_redis, mock_mongo, mock_logger)
        allow, reason = gate.check("g4", "P3")
        assert allow is True
        assert reason == "redis_unavailable"


class TestBreach:
    """
    Tests for ROUTER-BREACH-01: 100% budget breach enforcement.

    Covers: force_local on breach, P1 bypass, MongoDB enqueue_blocked write, auto-resume.
    Implementation owner: Plan 03.
    """

    def test_force_local_on_100pct(self, mock_redis, mock_mongo, mock_logger):
        """At 100% budget: BudgetGate.check() returns (False, 'budget_exceeded')."""
        mock_redis.hgetall.side_effect = None
        mock_redis.hgetall.return_value = {b"spent_usd": b"5.0", b"max_usd": b"5.0", b"status": b"ok"}
        gate = BudgetGate(mock_redis, mock_mongo, mock_logger)
        allow, reason = gate.check("g1", "P3")
        assert allow is False
        assert reason == "budget_exceeded"
        # record_breach was called → Mongo update_one fired with force_local=True
        calls = mock_mongo.fingpt_agents.agent_goals.update_one.call_args_list
        assert any(c.args[0] == {"goal_id": "g1"} and c.args[1]["$set"].get("force_local") is True for c in calls)

    def test_p1_bypass(self, mock_redis, mock_mongo, mock_logger):
        """P1 tasks bypass enqueue_blocked check (still gets force_local routing)."""
        mock_redis.hgetall.side_effect = None
        mock_redis.hgetall.return_value = {b"spent_usd": b"5.0", b"max_usd": b"5.0", b"status": b"exceeded"}
        gate = BudgetGate(mock_redis, mock_mongo, mock_logger)
        allow, reason = gate.check("g1", "P1")
        assert allow is True
        assert reason == "p1_bypass_force_local"

    def test_enqueue_blocked_written_to_mongo(self, mock_redis, mock_mongo, mock_logger):
        """record_breach() writes enqueue_blocked=True + force_local=True to agent_goals."""
        gate = BudgetGate(mock_redis, mock_mongo, mock_logger)
        gate.record_breach("g7")
        calls = mock_mongo.fingpt_agents.agent_goals.update_one.call_args_list
        assert any(c.args[1]["$set"].get("enqueue_blocked") is True for c in calls)
        assert any(c.args[1]["$set"].get("budget_status") == "exceeded" for c in calls)

    def test_auto_resume_on_reset(self, mock_redis, mock_mongo, mock_logger):
        """auto_resume_check() clears breach state when calendar date has rolled over."""
        from core.routing.budget_gate import _today_iso
        stale_date = "2020-01-01"   # not today
        mock_redis.hgetall.side_effect = None
        mock_redis.hgetall.return_value = {
            b"date": stale_date.encode(),
            b"status": b"exceeded",
            b"force_local": b"1",
            b"enqueue_blocked": b"1",
        }
        gate = BudgetGate(mock_redis, mock_mongo, mock_logger)
        gate.auto_resume_check("g8")
        # Mongo got the reset update
        calls = mock_mongo.fingpt_agents.agent_goals.update_one.call_args_list
        assert any(c.args[1]["$set"].get("force_local") is False for c in calls)
        assert any(c.args[1]["$set"].get("enqueue_blocked") is False for c in calls)
        assert any(c.args[1]["$set"].get("budget_status") == "ok" for c in calls)

    def test_record_warning_50pct(self, mock_redis, mock_mongo, mock_logger):
        """record_warning() at 50% writes budget_status='warning_50' to Mongo."""
        gate = BudgetGate(mock_redis, mock_mongo, mock_logger)
        gate.record_warning("g9", 0.5)
        calls = mock_mongo.fingpt_agents.agent_goals.update_one.call_args_list
        assert any(c.args[1]["$set"].get("budget_status") == "warning_50" for c in calls)

    def test_increment_spend_updates_three_aggregates(self, mock_redis, mock_mongo, mock_logger):
        """increment_spend() touches goal, agent_type, and system Redis aggregates."""
        gate = BudgetGate(mock_redis, mock_mongo, mock_logger)
        gate.increment_spend("g10", "agent_zero", 0.05)
        # Three keys touched: goal, agent, system
        keys_used = [c.args[0] for c in mock_redis.hincrbyfloat.call_args_list]
        assert "router:budget:goal:g10" in keys_used
        assert "router:budget:agent:agent_zero" in keys_used
        assert "router:budget:system" in keys_used


class TestAggregateGetters:
    """
    Tests for aggregate getter helpers consumed by Plan 05's multi-scope alert evaluation.

    Covers: agent_type and system scope {spent_usd, max_usd} pairs.
    Implementation owner: Plan 03.
    """

    def test_get_agent_type_aggregate_with_caps(self, mock_redis, mock_mongo, mock_logger):
        """get_agent_type_aggregate() returns spent from Redis + max from budget_caps."""
        mock_redis.hgetall.side_effect = None
        mock_redis.hgetall.return_value = {b"spent_usd": b"1.50", b"date": b"2026-05-01"}
        caps = {"agent_types": {"agent_zero": {"max_usd_per_day": 5.00}}, "system": {"max_usd_per_day": 50.00}}
        gate = BudgetGate(mock_redis, mock_mongo, mock_logger, budget_caps=caps)
        agg = gate.get_agent_type_aggregate("agent_zero")
        assert agg == {"spent_usd": 1.50, "max_usd": 5.00}

    def test_get_agent_type_aggregate_unknown_agent_max_zero(self, mock_redis, mock_mongo, mock_logger):
        """Unknown agent not in budget_caps returns max_usd=0.0 (signal: skip alert eval)."""
        mock_redis.hgetall.side_effect = None
        mock_redis.hgetall.return_value = {b"spent_usd": b"0.10"}
        caps = {"agent_types": {"agent_zero": {"max_usd_per_day": 5.00}}, "system": {}}
        gate = BudgetGate(mock_redis, mock_mongo, mock_logger, budget_caps=caps)
        agg = gate.get_agent_type_aggregate("future_agent")
        assert agg["max_usd"] == 0.0   # signal: skip alert eval for this scope

    def test_get_system_aggregate(self, mock_redis, mock_mongo, mock_logger):
        """get_system_aggregate() returns spent from Redis + max from budget_caps['system']."""
        mock_redis.hgetall.side_effect = None
        mock_redis.hgetall.return_value = {b"spent_usd": b"12.34"}
        caps = {"agent_types": {}, "system": {"max_usd_per_day": 50.00}}
        gate = BudgetGate(mock_redis, mock_mongo, mock_logger, budget_caps=caps)
        agg = gate.get_system_aggregate()
        assert agg == {"spent_usd": 12.34, "max_usd": 50.00}

    def test_aggregates_fail_open_on_redis_error(self, mock_redis, mock_mongo, mock_logger):
        """Redis errors in aggregate getters fail open (spent=0.0, max from caps)."""
        mock_redis.hgetall.side_effect = ConnectionError("redis down")
        caps = {"agent_types": {"agent_zero": {"max_usd_per_day": 5.00}}, "system": {"max_usd_per_day": 50.00}}
        gate = BudgetGate(mock_redis, mock_mongo, mock_logger, budget_caps=caps)
        assert gate.get_agent_type_aggregate("agent_zero") == {"spent_usd": 0.0, "max_usd": 5.00}
        assert gate.get_system_aggregate() == {"spent_usd": 0.0, "max_usd": 50.00}
