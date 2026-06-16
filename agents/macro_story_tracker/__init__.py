"""Phase 87 Wave 4b — macro_story_tracker background agent package.

Hourly long-running agent maintaining evolving macro "story" objects
(e.g., "inflation persistence trend emerging"). Polls last-6h releases via
the VM101 typed economic_event API (Phase 47.2 lock — no parquet reads),
pulls top-K prior episodes via the Plan 87-07 EpisodicMemoryService
(message_loop_prompts_before_b6 hook), detects multi-indicator joint
patterns (REQ-87-9), CREATEs / REINFORCEs / RETIREs macro_story rows on
VM101 Postgres.

Ships as docker-compose sibling service ``vm107-macro-story-tracker``
per LOCK-8 / REQ-87-8 / feedback_mgmt_commands_need_compose_service.
Plan 74-03 lost the observation pipeline by skipping this lock; Plan
87-08 honours it from day one.
"""
from .skill_multi_indicator_pattern import (
    ANCHOR_INDICATORS,
    detect_joint_pattern,
    joint_pattern_prompt_directive,
)
from .skill_story_update import (
    CONFIDENCE_FLOOR,
    MAX_ACTIVE_STORIES,
    SIMILARITY_THRESHOLD,
    StoryUpdateDecision,
    check_retirement,
    decide_update,
)

__all__ = [
    "ANCHOR_INDICATORS",
    "CONFIDENCE_FLOOR",
    "MAX_ACTIVE_STORIES",
    "SIMILARITY_THRESHOLD",
    "StoryUpdateDecision",
    "check_retirement",
    "decide_update",
    "detect_joint_pattern",
    "joint_pattern_prompt_directive",
]
