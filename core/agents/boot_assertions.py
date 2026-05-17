"""Phase 47.6 LD-8: startup defense-in-depth boot guards.

assert_no_filesystem_walkers() scans protected paths for walker call signatures.
Narrowed to _11_tools_prompt.py only (Pitfall 7 — skills/MCP/secret walkers
legitimately walk directories and must NOT be flagged).

Called from VM107/preload.py AFTER initialize_capability_registry() so the
registry is the discovery authority and walkers cannot have crept back in.
"""
from __future__ import annotations

from pathlib import Path

# These call signatures indicate capability-discovery walker code.
# Narrowed to the specific scanner pattern used in _11_tools_prompt.py
# (Pitfall 7: skills walkers, MCP config walkers, and secret loaders also
# call directory-walk helpers — do NOT flag them).
WALKER_CALL_FRAGMENTS: list[str] = [
    "files.get_unique_filenames_in_dirs",
]

# Only these paths are checked. Expanding this list should require a code review.
PROTECTED_PATHS: list[str] = [
    "extensions/python/system_prompt/_11_tools_prompt.py",
]


def assert_no_filesystem_walkers(repo_root: Path) -> None:
    """Raise AssertionError if capability-discovery walker code is found in protected paths.

    This is a static-file scan — does NOT require the registry to be live.
    Run after initialize_capability_registry() to maintain coherent boot ordering.

    Args:
        repo_root: Path to the VM107 repository root (parent of extensions/).

    Raises:
        AssertionError: If any WALKER_CALL_FRAGMENTS fragment is found in
                        any PROTECTED_PATHS file. This means someone re-added
                        filesystem walker code to a capability-discovery path.
        FileNotFoundError: If a protected path does not exist (mis-configuration).
    """
    for rel in PROTECTED_PATHS:
        target = repo_root / rel
        if not target.exists():
            raise FileNotFoundError(
                f"Boot assertion: protected path {rel!r} does not exist under {repo_root}. "
                f"Update PROTECTED_PATHS if the file was intentionally moved."
            )
        source = target.read_text(encoding="utf-8")
        for fragment in WALKER_CALL_FRAGMENTS:
            assert fragment not in source, (
                f"Filesystem walker REGRESSION detected in {rel}: "
                f"contains {fragment!r}. "
                f"Capability discovery must flow through CapabilityRegistry only (LD-8). "
                f"Remove the walker call and use CapabilityRegistry.get_index_for_profile() instead."
            )
