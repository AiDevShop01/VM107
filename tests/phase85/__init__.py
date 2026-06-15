# Phase 85 test package.
#
# RETIRED TESTS:
# - test_indicator_description_backfill.py (removed 2026-06-15, Phase 85.1 Plan 04)
#   Replacement: VM107/tests/phase85_1/test_backfill_after_fix.py
#   Reason: The original test mocked agent_module.run_agent successfully, hiding the
#   AttributeError: module 'agent' has no attribute 'run_agent' bug surfaced in Phase 85
#   UAT. The replacement exercises the real _dispatch_agent_sync path from Plan 02.
