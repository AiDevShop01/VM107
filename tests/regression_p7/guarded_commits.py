"""Single-source guarded-commit map for the Phase 139 F5 regression suite (SC-1).

`GUARDED_COMMITS` maps each F5 `test_id` to the fix commit sha(s) it guards on
branch `develop`. This map is the SINGLE SOURCE OF TRUTH read by BOTH:

  1. the F5 test annotations (each test names the sha(s) it locks), and
  2. the D-03 revert harness (`revert_guard.py`, Plan 05), which for each
     (test, sha) reverts the sha in a throwaway `git worktree`, runs the guarding
     test EXPECTING RED, then restores.

A stale entry MUST FAIL LOUD, never silent-pass: if the revert harness cannot
cleanly revert a listed sha on current `develop` (several fixes span multiple
commits and were later refactored — `get_tool` moved in 138-05, the qdrant
factory consolidated in 138-04), that is a HARD FAILURE
("cannot cleanly revert <sha> on develop — guarded-commit map is stale"), not a
skipped or passing test. See 139-RESEARCH.md §D-03 / Pitfall 3.

Tier-2 note: `test_p1_loop_stall`, `test_p3d1_tool_load`, and the
`test_p3d3_degraded_cause` Half-C sub-case are `requires_deps` (they import the
heavy memory/agent/model-call modules), so they run only under the Tier-2 CI venv
(`VM107/.venv`, marker registered in `pytest.ini` by Task 2). The host-clean fast
loop runs `-m "not requires_deps"`.

Shas verified in-session against `git -C VM107 log` (139-RESEARCH.md L304-310).
"""
from __future__ import annotations

GUARDED_COMMITS: dict[str, list[str]] = {
    # P0 — cancel whole-boot watchdog on the ready path (+ floor MCP init_timeout).
    "test_p0_boot_restart": ["fe21a20", "be52083"],
    # P1 — off-loop embed + offloaded query_points + gathered concurrent recall.
    "test_p1_loop_stall": ["7e25765", "ac6e4dc", "78f7800"],
    # P3-D1 — FailedToLoad sentinel + tri-state (+ 138-05 extract get_tool).
    "test_p3d1_tool_load": ["0321329", "dcbe600"],
    # P3-D3 — freshen bus in search + render DEGRADED + context-scope.
    #   The NEW D-04/D-05 cause-carrying commit is appended by Plan 02.
    "test_p3d3_degraded_cause": ["2a7ff89", "35e23ee", "514e4ca", "e01bd54"],
    # P2 — time clients + factory liveness degrade + neutralize retry loop.
    "test_p2_chaos": ["747117a", "519f522", "0050c0d"],
}
