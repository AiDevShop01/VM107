"""
AffinityMap — YAML affinity map loader with double-default fallback.

Loads the affinity block from model_routing.yaml and provides deterministic
per-call lookup with two levels of fallback:

    affinity[agent_id][task_type]      (exact match)
    -> affinity[agent_id]["default"]   (agent exists, task_type unknown)
    -> affinity["default"]["default"]  (agent unknown entirely)

Each entry returns a dict: {primary: [...], secondary: [...], local: [...]}

Implementation plan: Plan 02 replaces stubs with real YAML parsing + validation.

Anti-pattern: Router NEVER invents a task_type taxonomy. Task types from Phase 42's
TaskModel.task_type field are used VERBATIM. Unknown types fall through to default.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("router.affinity")


class AffinityMap:
    """
    Affinity map loader and lookup engine.

    Wraps the affinity block from model_routing.yaml:
        affinity:
          agent_zero:
            analysis:
              primary: [...]
              secondary: [...]
              local: [...]
            default:
              primary: [...]
              ...
          default:
            default:
              primary: [...]
              ...

    Provides deterministic lookup with double-default fallback so router
    always returns a candidate set regardless of (agent_id, task_type) pair.

    All methods raise NotImplementedError until Plan 02 implements them.
    Constructor accepts no required args so it can be instantiated in tests.
    """

    def __init__(self, affinity_data: dict | None = None) -> None:
        """
        Initialize AffinityMap with raw affinity dict from YAML.

        Args:
            affinity_data: The 'affinity' block from model_routing.yaml.
                          None creates an empty map (no lookup possible).
        """
        self._data = affinity_data or {}

    @classmethod
    def from_yaml(cls, path: str) -> "AffinityMap":
        """
        Load AffinityMap from model_routing.yaml.

        Validates that 'default.default' entry exists (required for double-fallback).

        Args:
            path: Absolute path to model_routing.yaml

        Returns:
            AffinityMap instance loaded from YAML.

        Raises:
            NotImplementedError: Until Plan 02 implements YAML loading.
        """
        raise NotImplementedError("Phase 43 Plan 02: AffinityMap.from_yaml() pending")

    def lookup(self, agent_id: str, task_type: str) -> dict:
        """
        Look up model chain for (agent_id, task_type) pair.

        Fallback chain:
            1. affinity[agent_id][task_type]      — exact match
            2. affinity[agent_id]["default"]      — agent-level fallback
            3. affinity["default"]["default"]     — global fallback

        The reason for the fallback path is logged but not returned here;
        router records it in the decision reason[] list.

        Args:
            agent_id: Agent identifier (e.g. "agent_zero")
            task_type: Task type string (verbatim from TaskModel.task_type)

        Returns:
            Dict with keys: primary (list[str]), secondary (list[str]), local (list[str])

        Raises:
            NotImplementedError: Until Plan 02 implements lookup logic.
        """
        raise NotImplementedError("Phase 43 Plan 02: AffinityMap.lookup() pending")
