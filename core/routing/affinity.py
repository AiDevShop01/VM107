"""
AffinityMap — YAML affinity map loader with double-default fallback.

Loads the affinity block from model_routing.yaml and provides deterministic
per-call lookup with two levels of fallback:

    affinity[agent_id][task_type]      (exact match)
    -> affinity[agent_id]["default"]   (agent exists, task_type unknown)
    -> affinity["default"]["default"]  (agent unknown entirely)

Each entry returns a dict: {primary: [...], secondary: [...], local: [...]}

Anti-pattern: Router NEVER invents a task_type taxonomy. Task types from Phase 42's
TaskModel.task_type field are used VERBATIM. Unknown types fall through to default.
"""
from __future__ import annotations

import logging
from pathlib import Path

import yaml

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

    budget_caps is exposed for Plan 03's BudgetGate.get_agent_type_aggregate /
    get_system_aggregate (max_usd values are config-driven, not state).
    """

    def __init__(self, raw: dict) -> None:
        """
        Initialize AffinityMap with the full parsed YAML dict.

        Validates mode_weights sum to 1.0 at construction time.

        Args:
            raw: Full parsed model_routing.yaml dict.

        Raises:
            ValueError: If any mode_weights row sums to != 1.0.
            KeyError: If required 'affinity' or 'mode_weights' keys are missing.
        """
        self._validate_mode_weights(raw.get("mode_weights", {}))
        self.raw = raw
        self.affinity = raw["affinity"]
        self.models = raw.get("models", {})
        self.mode_weights = raw["mode_weights"]
        self.stabilization_safe = set(raw.get("stabilization_safe_models", []))
        # budget_caps consumed by Plan 03's BudgetGate aggregate getters and
        # Plan 05's alert evaluation for agent_type + system scopes.
        self.budget_caps = raw.get("budget_caps", {"agent_types": {}, "system": {}})

    @classmethod
    def from_yaml(cls, path: str) -> "AffinityMap":
        """
        Load AffinityMap from model_routing.yaml.

        Validates that mode_weights sum to 1.0 and 'affinity.default.default'
        entry exists (required for double-fallback guarantee).

        Args:
            path: Absolute path to model_routing.yaml

        Returns:
            AffinityMap instance loaded from YAML.

        Raises:
            ValueError: If mode_weights sums are invalid.
            KeyError: If required YAML keys are missing.
        """
        raw = yaml.safe_load(Path(path).read_text())
        return cls(raw)

    @staticmethod
    def _validate_mode_weights(weights: dict) -> None:
        """Validate that each mode's weights sum to exactly 1.0."""
        for mode, w in weights.items():
            total = w["quality"] + w["cost"] + w["latency"]
            if abs(total - 1.0) > 1e-9:
                raise ValueError(
                    f"mode_weights[{mode}] must sum to 1.0, got {total} "
                    f"(quality={w['quality']}, cost={w['cost']}, latency={w['latency']})"
                )

    def lookup(self, agent_id: str, task_type: str) -> dict:
        """
        Look up model chain for (agent_id, task_type) pair.

        Fallback chain:
            1. affinity[agent_id][task_type]      — exact match
            2. affinity[agent_id]["default"]      — agent-level fallback
            3. affinity["default"]["default"]     — global fallback

        Args:
            agent_id: Agent identifier (e.g. "agent_zero")
            task_type: Task type string (verbatim from TaskModel.task_type)

        Returns:
            Dict with keys: primary (list[str]), secondary (list[str]), local (list[str])

        Raises:
            KeyError: If resolved chain is missing required tiers.
            ValueError: If resolved chain has an empty local tier.
        """
        agent_block = self.affinity.get(agent_id)
        if agent_block is None:
            logger.debug(
                "agent_id %r not in affinity map, using default.default fallback",
                agent_id,
            )
            chain = self.affinity["default"]["default"]
        else:
            chain = agent_block.get(task_type)
            if chain is None:
                logger.debug(
                    "task_type %r not in affinity[%r], using agent default fallback",
                    task_type,
                    agent_id,
                )
                chain = agent_block.get("default") or self.affinity["default"]["default"]

        # Defensive validation: ensure all three tiers present
        for tier in ("primary", "secondary", "local"):
            if tier not in chain:
                raise KeyError(
                    f"Resolved affinity chain for ({agent_id!r}, {task_type!r}) "
                    f"is missing tier {tier!r}"
                )
        if not chain["local"]:
            raise ValueError(
                f"Resolved affinity chain for ({agent_id!r}, {task_type!r}) "
                f"has empty local tier (CONTEXT.md: local tier always present)"
            )

        return dict(chain)

    def get_model_meta(self, model_id: str) -> dict:
        """
        Return tier/quality_score/latency_ms/cost_per_1k_output_usd from models catalog.

        Args:
            model_id: Model identifier as in model_routing.yaml models block.

        Returns:
            Dict with model metadata fields.

        Raises:
            KeyError: If model_id is not in the catalog.
        """
        meta = self.models.get(model_id)
        if meta is None:
            raise KeyError(
                f"model {model_id!r} not in catalog (model_routing.yaml -> models)"
            )
        return meta

    def is_stabilization_safe(self, model_id: str) -> bool:
        """Return True if model is in the stabilization_safe_models list."""
        return model_id in self.stabilization_safe
