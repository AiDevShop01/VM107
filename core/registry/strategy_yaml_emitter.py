"""Phase 48 accepted-strategy registry YAML emitter.

REGISTER_CAPABILITY: type=service, id=strategy_yaml_emitter, path=VM107/core/registry/strategy_yaml_emitter.py

REQ-48-D11. CONTEXT § Decision 11.

When the refinement orchestrator's acceptance path promotes a StrategySpec
to the ``accepted_strategies`` WORM collection, this module auto-generates
the matching Phase 47.6 registry entry at
``VM107/registry/strategy/<accepted_strategy_id>.yaml``.

YAML schema (passes ``core.registry.validation.validate_schemas`` Stage 2):
  - REGISTER_CAPABILITY header comment.
  - id == accepted_strategy_id (must equal filename without .yaml).
  - type: strategy
  - status: real  (Phase 47.6 CapabilityStatus — the registry capability is
    real-and-shipped; the **strategy-specific** lifecycle enum from
    CONTEXT § Decision 11 — {accepted, deprecated, shadow, experimental} —
    lives in the separate ``strategy_lifecycle_status`` field so the two
    enums don't collide).
  - strategy_lifecycle_status: accepted (Decision 11 V1 default).
  - shipped: 48, phase: 48, producer: VM107.
  - allowed_execution_modes: [RESEARCH] (V1 default — Phase 51 will mutate).
  - strategy_family, root_hypothesis_id, refinement_loop_id, accepted_at,
    accepted_registry_snapshot_hash, final_* artifact ids (references to
    canonical Mongo truth — NEVER duplicate the full Mongo doc).
  - impact_on_decision: HIGH.
  - allowed_agent_profiles: [] (research-mode default; downstream phases
    extend when promoting beyond RESEARCH).

WORM enforcement at the registry level: ``emit_strategy_yaml`` refuses to
overwrite an existing file for the same accepted_strategy_id and raises
``StrategyYAMLAlreadyExists``. Combined with the Mongo-layer ``_worm_locked``
flag stamped in ``acceptance_path.accept_strategy``, this gives the two
mutually-reinforcing WORM checks Decision 11 requires for V1.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

# Default registry strategy directory. Tests override via the ``output_dir``
# kwarg; production callers (acceptance_path) point at the in-tree
# ``VM107/registry/strategy/`` location.
_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_REGISTRY_STRATEGY_DIR: Path = _VM107_ROOT / "registry" / "strategy"


class StrategyYAMLAlreadyExists(RuntimeError):
    """Raised when emit_strategy_yaml would overwrite an existing strategy YAML.

    Registry-layer WORM enforcement: a second emission for the same
    accepted_strategy_id is a contract violation.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__(
            f"Strategy registry YAML already exists: {path}. "
            "Accepted strategies are write-once; refusing to overwrite."
        )


def _derive_risk_class(accepted_doc: dict[str, Any]) -> str:
    """Best-effort risk class derivation from the strategy_family.

    V1: ``BREAKOUT`` / ``VOLATILITY_EXPANSION`` => HIGH; ``MEAN_REVERSION`` /
    ``AUCTION_ROTATION`` => MEDIUM; ``TREND_CONTINUATION`` => MEDIUM; default
    MEDIUM. Phase 51/53 may compute this from BacktestResult.max_drawdown
    directly; until then a family-tier mapping keeps the YAML self-describing.
    """
    family = accepted_doc.get("strategy_family", "")
    high = {"BREAKOUT", "VOLATILITY_EXPANSION"}
    if family in high:
        return "HIGH"
    return "MEDIUM"


def _build_yaml_payload(accepted_doc: dict[str, Any]) -> dict[str, Any]:
    """Project the accepted_strategies Mongo doc to the registry YAML shape.

    Mongo doc is canonical truth — the YAML stores discovery-relevant
    references and metadata, never the full Mongo doc.
    """
    aid = accepted_doc["accepted_strategy_id"]
    return {
        "id": aid,
        "type": "strategy",
        # Phase 47.6 CapabilityStatus — the registry-level "is this real?" flag.
        "status": "real",
        # Decision 11 lifecycle enum — separate field to avoid colliding with
        # the registry's CapabilityStatus enum.
        "strategy_lifecycle_status": "accepted",
        "shipped": 48,
        "phase": 48,
        "producer": "VM107",
        "name": aid,
        "description": (
            "Accepted refinement-loop strategy auto-promoted by "
            "refinement_orchestrator. Mongo doc accepted_strategies/"
            f"{aid} is the canonical truth."
        ),
        "version": "1.0.0",
        "strategy_family": accepted_doc["strategy_family"],
        "root_hypothesis_id": accepted_doc["root_hypothesis_id"],
        "refinement_loop_id": accepted_doc["refinement_loop_id"],
        "accepted_strategy_id": aid,
        "accepted_registry_snapshot_hash": accepted_doc[
            "accepted_registry_snapshot_hash"
        ],
        "final_strategy_spec_id": accepted_doc["final_strategy_spec_id"],
        "final_code_module_id": accepted_doc["final_code_module_id"],
        "final_backtest_result_id": accepted_doc["final_backtest_result_id"],
        "final_critic_verdict_id": accepted_doc["final_critic_verdict_id"],
        "allowed_execution_modes": ["RESEARCH"],
        "supported_instruments": [],
        "validated_regimes": [],
        "risk_class": _derive_risk_class(accepted_doc),
        "impact_on_decision": "HIGH",
        "deprecated": False,
        "hard_scoped": False,
        "allowed_agent_profiles": [],
        "related_capabilities": ["refinement_orchestrator"],
        "tags": [
            "phase-48",
            "strategy",
            "accepted",
            "refinement_loop",
            f"family-{accepted_doc['strategy_family'].lower()}",
        ],
    }


def emit_strategy_yaml(
    accepted_strategy_doc: dict[str, Any],
    *,
    output_dir: Path | None = None,
) -> Path:
    """Write the accepted-strategy registry YAML and return its Path.

    Args:
        accepted_strategy_doc: dict matching the CONTEXT § Decision 11 shape
            (must include ``accepted_strategy_id`` + the references this
            module projects into the YAML payload).
        output_dir: Optional override of the registry/strategy/ destination
            (used by tests; production callers should leave None).

    Returns:
        Path to the written YAML file.

    Raises:
        StrategyYAMLAlreadyExists: a file already exists at the destination
            (registry-layer WORM enforcement).
        KeyError: ``accepted_strategy_doc`` is missing a required field.
    """
    dest_dir = output_dir if output_dir is not None else DEFAULT_REGISTRY_STRATEGY_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    aid = accepted_strategy_doc["accepted_strategy_id"]
    path = dest_dir / f"{aid}.yaml"

    if path.exists():
        raise StrategyYAMLAlreadyExists(path)

    payload = _build_yaml_payload(accepted_strategy_doc)

    header = (
        f"# REGISTER_CAPABILITY: type=strategy, id={aid}, "
        f"path=VM107/registry/strategy/{aid}.yaml\n"
    )
    body = yaml.safe_dump(payload, sort_keys=False, default_flow_style=False)
    path.write_text(header + body)
    return path


__all__ = [
    "DEFAULT_REGISTRY_STRATEGY_DIR",
    "StrategyYAMLAlreadyExists",
    "emit_strategy_yaml",
]
