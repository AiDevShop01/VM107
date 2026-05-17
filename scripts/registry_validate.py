"""Standalone registry validation CLI.

Validates all capability YAMLs in the registry through the full 7-stage pipeline
and reports the snapshot hash + entry count on success, or the validation error
on failure.

Usage:
    CAPABILITY_REGISTRY_ROOT=/path/to/registry python -m scripts.registry_validate

Exit codes:
    0 — validation passed; prints "OK: snapshot_hash=<64-hex> entries=<N>"
    1 — validation failed; prints "FAIL: <RegistryValidationError details>"
    2 — CAPABILITY_REGISTRY_ROOT env var not set

Environment variables:
    CAPABILITY_REGISTRY_ROOT (required): Absolute path to the registry directory.
        Must contain type subdirectories (tool/, signal/, skill/, etc.).
        No fallback — fail-fast per CONTEXT.md env-driven config lock.

Example:
    cd VM107
    CAPABILITY_REGISTRY_ROOT="$(pwd)/registry" python -m scripts.registry_validate

    OK: snapshot_hash=a3f9b2... entries=155
"""

import os
import sys
from pathlib import Path

# Ensure VM107 root is on sys.path so `core.*` imports resolve
_VM107_ROOT = Path(__file__).resolve().parent.parent
_vm107_str = str(_VM107_ROOT)
if _vm107_str not in sys.path:
    sys.path.insert(0, _vm107_str)

from core.registry.capability_registry import CapabilityRegistry  # noqa: E402
from fingpt_core.contracts.capability_registry import (  # noqa: E402
    RegistryValidationError,
)


def main() -> None:
    """Entry point for registry validation CLI."""
    try:
        root = Path(os.environ["CAPABILITY_REGISTRY_ROOT"])
    except KeyError:
        print(
            "ERROR: CAPABILITY_REGISTRY_ROOT env var not set. "
            "Set it to the absolute path of your registry directory.",
            file=sys.stderr,
        )
        sys.exit(2)

    if not root.is_dir():
        print(
            f"ERROR: CAPABILITY_REGISTRY_ROOT={root} is not a directory or does not exist.",
            file=sys.stderr,
        )
        sys.exit(2)

    try:
        reg = CapabilityRegistry.initialize(root)
    except RegistryValidationError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"FAIL (unexpected): {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)

    print(
        f"OK: snapshot_hash={reg.snapshot_hash} "
        f"entries={len(reg.snapshot.entries)}"
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
