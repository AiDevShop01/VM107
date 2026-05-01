"""
Router pipeline tests — covers ROUTER-PIPELINE-01, ROUTER-FALLBACK-01,
ROUTER-BRAIN-01, ROUTER-PEAK-01, ROUTER-LOG-01, ROUTER-HOOKS-01.

Wave 1 plans remove xfail from their owned test groups.
Plan 02 owns: TestPeakSchedule.test_perth_peak_window_detection, test_from_yaml_constructs
Plan 05 owns: all remaining xfail tests.

Per-task verification map commands (from VALIDATION.md):
    pytest tests/routing/test_router.py::TestPipeline -x -q
    pytest tests/routing/test_router.py::TestFallback -x -q
    pytest tests/routing/test_router.py::TestBrainFilter -x -q
    pytest tests/routing/test_router.py::TestPeakSchedule -x -q
    pytest tests/routing/test_router.py::TestLogging -x -q
    pytest tests/routing/test_router.py::TestHooks -x -q
"""
import pytest


class TestPipeline:
    """
    Tests for ROUTER-PIPELINE-01: 8-step deterministic routing pipeline.

    Covers: pipeline step order, budget gate hard stop, full pipeline integration.
    Implementation owner: Plan 05.
    """

    def test_eight_step_order(self, mock_agent, mock_runner, mock_redis, mock_mongo):
        """Pipeline executes all 8 steps in correct order (load→gate→select→brain→latency→peak→chain→log)."""
        pytest.xfail("Plan 05: pipeline implementation pending")

    def test_budget_gate_hard_stop(self, mock_agent, mock_runner, mock_redis, mock_mongo):
        """When budget gate returns False, pipeline skips steps 3-7 and returns local-only chain."""
        pytest.xfail("Plan 05: pipeline implementation pending")


class TestFallback:
    """
    Tests for ROUTER-FALLBACK-01: 3-tier primary/fallback chain construction.

    Covers: local tier always present, chain integrity under peak, chain minimum length.
    Implementation owner: Plan 05.
    """

    def test_chain_always_has_local(self):
        """Fallback chain always includes at least one local-tier model as last entry."""
        pytest.xfail("Plan 05: fallback construction pending")

    def test_peak_preserves_chain(self):
        """Peak mode shifts primary to secondary tier but full chain length preserved."""
        pytest.xfail("Plan 05: fallback construction pending")


class TestBrainFilter:
    """
    Tests for ROUTER-BRAIN-01: brain-mode filter application.

    Covers: stabilization hard filter, exploration soft preference, exploitation behavior.
    Implementation owner: Plan 05.
    """

    def test_stabilization_hard_filter(self):
        """Stabilization mode drops models tagged expensive or unsafe from candidate set."""
        pytest.xfail("Plan 05: brain filter pending")

    def test_exploration_soft_preference(self):
        """Exploration mode retains full candidate set and applies quality weight boost."""
        pytest.xfail("Plan 05: brain filter pending")


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

    def test_peak_hard_shift(self):
        """Peak hours apply hard tier-shift: secondary tier becomes effective primary."""
        pytest.xfail("Plan 05: peak modifier integration pending")

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


class TestLogging:
    """
    Tests for ROUTER-LOG-01: mandatory per-call decision + cost logging.

    Covers: decision log has 8 required fields, cost record has 5 required fields.
    Implementation owner: Plan 05.
    """

    def test_decision_log_has_eight_fields(self):
        """Decision log emitted to router_decisions with all 8 mandatory fields present."""
        pytest.xfail("Plan 05: decision log pending")

    def test_cost_record(self):
        """CostRecord written after call with 5 required fields (task_id, model, tokens, cost_usd, latency_ms)."""
        pytest.xfail("Plan 05: cost record pending")


class TestHooks:
    """
    Tests for ROUTER-HOOKS-01: extension-only hook integration.

    Covers: before_main_llm_call stores decision in params_temporary,
            chat_model_call_after updates Redis aggregates.
    Implementation owner: Plan 05.
    """

    def test_before_main_llm_call_stashes_decision(self, mock_agent):
        """before_main_llm_call extension calls Router.decide() and stores result in loop_data.params_temporary."""
        pytest.xfail("Plan 05: hook integration pending")

    def test_post_call_update(self, mock_agent, mock_redis, mock_mongo):
        """chat_model_call_after extension updates Redis budget aggregate after each call."""
        pytest.xfail("Plan 05: post-call hook pending")
