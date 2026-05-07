"""Phase 47.2-03 strategy YAML loader.

Loads strategy definitions from `agents/agent0/strategies/<id>.yaml` and
returns a typed `StrategyDefinition` (Pydantic, frozen, extra='forbid').

Design locks (from `.planning/phases/47.2-trade-context-tooling-wave-3-inserted/47.2-CONTEXT.md`):

- ALWAYS-FRESH per call. The file is re-read on every invocation so traders
  can edit YAML without redeploying VM107. No in-memory cache, no startup load.
- Strict Pydantic validation (RESEARCH OQ-6): malformed YAML or schema
  violations raise `MalformedStrategyError`; missing files raise
  `StrategyNotFoundError`.
- Reuses `helpers.yaml.loads` (PyYAML `safe_load` wrapper) and
  `helpers.files.get_abs_path` so the resolution behaves identically to
  every other VM107 file lookup.

Phase 47.5 will add directory scanning + dynamic strategy registry. The
locked YAML schema (see `StrategyDefinition`) MUST stay stable so 47.5
doesn't have to migrate existing files.
"""

from __future__ import annotations

from pathlib import Path

from fingpt_core.contracts.agents.strategy_definition import StrategyDefinition

from helpers import yaml as yaml_helper
from helpers.files import get_abs_path

_STRATEGY_DIR_REL = "agents/agent0/strategies"


class StrategyNotFoundError(KeyError):
    """Raised when the requested strategy_id has no matching YAML file."""


class MalformedStrategyError(ValueError):
    """Raised when YAML is invalid or fails Pydantic schema validation."""


def load_strategy(strategy_id: str) -> StrategyDefinition:
    """Load a strategy from `agents/agent0/strategies/{strategy_id}.yaml`.

    Always-fresh: every call re-reads disk (no cache). Phase 47.2 lock
    so traders can edit strategy YAML without redeploying VM107.

    Args:
        strategy_id: Strategy identifier. Must match the filename stem
            AND the `id` field inside the YAML file.

    Returns:
        Parsed and validated `StrategyDefinition`.

    Raises:
        StrategyNotFoundError: If the YAML file does not exist.
        MalformedStrategyError: If YAML parsing fails OR schema validation
            fails OR the file's `id` field doesn't match `strategy_id`.
    """
    path = Path(get_abs_path(_STRATEGY_DIR_REL, f"{strategy_id}.yaml"))
    if not path.is_file():
        raise StrategyNotFoundError(
            f"Strategy '{strategy_id}' not found at {path}"
        )

    try:
        text = path.read_text(encoding="utf-8")
        data = yaml_helper.loads(text)
    except Exception as exc:
        raise MalformedStrategyError(
            f"Strategy '{strategy_id}' YAML parse failed: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise MalformedStrategyError(
            f"Strategy '{strategy_id}' YAML root is not a mapping (got "
            f"{type(data).__name__})"
        )

    # Cross-check: file's internal id MUST match the requested strategy_id.
    # Catches accidental copy-paste / rename mistakes early.
    if data.get("id") != strategy_id:
        raise MalformedStrategyError(
            f"Strategy file id={data.get('id')!r} does not match requested "
            f"{strategy_id!r}"
        )

    # Strict Pydantic validation per OQ-6 — schema violations are loud failures.
    try:
        return StrategyDefinition(**data)
    except Exception as exc:
        raise MalformedStrategyError(
            f"Strategy '{strategy_id}' schema validation failed: {exc}"
        ) from exc
