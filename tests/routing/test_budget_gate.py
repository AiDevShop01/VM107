"""
Budget gate tests — covers ROUTER-BUDGET-01 + ROUTER-BREACH-01.

All tests xfail until Plan 03 implements BudgetGate Redis read + breach handler.

Per-task verification map commands (from VALIDATION.md):
    pytest tests/routing/test_budget_gate.py -x -q
    pytest tests/routing/test_budget_gate.py::TestBreach -x -q
    pytest tests/routing/test_budget_gate.py::TestBreach::test_p1_bypass -x -q
"""
import pytest


class TestBudgetGate:
    """
    Tests for ROUTER-BUDGET-01: per-goal budget gate at routing time.

    Covers: Redis aggregate read, MongoDB cache-miss fallback, unconstrained goals.
    Implementation owner: Plan 03.
    """

    def test_redis_aggregate_read(self, mock_redis):
        """BudgetGate.check() reads from router:budget:goal:{goal_id} HSET key in Redis."""
        pytest.xfail("Plan 03: budget gate pending")

    def test_cache_miss_reads_mongo_once(self, mock_redis, mock_mongo):
        """On Redis cache miss, BudgetGate queries MongoDB once to initialize Redis key."""
        pytest.xfail("Plan 03: cache miss path pending")

    def test_no_budget_set_allows(self, mock_redis):
        """Goals without budget_max_cost_usd set are allowed (no constraint = no block)."""
        pytest.xfail("Plan 03: unconstrained goal pending")


class TestBreach:
    """
    Tests for ROUTER-BREACH-01: 100% budget breach enforcement.

    Covers: force_local on breach, P1 bypass, MongoDB enqueue_blocked write, auto-resume.
    Implementation owner: Plan 03.
    """

    def test_force_local_on_100pct(self, mock_redis, mock_mongo):
        """At 100% budget: BudgetGate.check() returns (False, 'exceeded_force_local')."""
        pytest.xfail("Plan 03: breach handler pending")

    def test_p1_bypass(self, mock_redis, mock_mongo):
        """P1 tasks bypass enqueue_blocked check (but still force_local if budget exceeded)."""
        pytest.xfail("Plan 03: P1 bypass pending")

    def test_enqueue_blocked_written_to_mongo(self, mock_mongo):
        """record_breach() writes enqueue_blocked=True + force_local=True to agent_goals."""
        pytest.xfail("Plan 03: breach state persistence pending")

    def test_auto_resume_on_reset(self, mock_redis, mock_mongo):
        """auto_resume_check() clears breach state when calendar date has rolled over."""
        pytest.xfail("Plan 03: auto-resume pending")
