# Phase 89 Plan 01 — response_self_check extension slot package marker.
# Extensions in this directory fire after LLM response stream ends,
# BEFORE reasoning_stream_end (which persists the B1 artifact).
# Ordering is deterministic: extensions sorted by filename prefix.
# _10_b5_self_check.py fires first in this slot (slot 10 of response_self_check).
