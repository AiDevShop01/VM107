"""Plan 87-14 deploy-gate persistence package for the macro_story tracker.

Holds ``macro_story_repo`` — the tradetracker.macro_story DAL imported by
``scripts/run_macro_story_tracker.py`` (``from persist.macro_story_repo import
MacroStoryRepo``). Kept as its own top-level package to match the runner's
import path exactly.
"""
