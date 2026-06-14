"""VM107 root conftest — ensures VM107 root is in sys.path for all tests.

This conftest runs before pytest collects any test, so the VM107 tools
package is importable as `tools.xxx` in all test files regardless of
which directory pytest starts collecting from first.

Also clears any namespace-package `tools` entry that Python may have
cached from site-packages before VM107 was injected (avoids shadowing).

Phase 85.1 addition: also adds the parent of VM107 (FinGPT/) to sys.path so
that Phase 85.1 tests can import via the ``VM107.*`` package path
(e.g. ``from VM107.workers.task_dispatcher import parse_and_persist``).
This mirrors how the Docker container mounts VM107 as a sub-package of the
FinGPT namespace.
"""
from __future__ import annotations

import sys
from pathlib import Path

_VM107_ROOT = Path(__file__).resolve().parent
_FINGPT_ROOT = _VM107_ROOT.parent  # /Volumes/ HardDrive/FinGPT/

# Ensure VM107 root is at the FRONT of sys.path so `tools.*` resolves
# to VM107/tools/ before any site-packages namespace package.
_vm107_str = str(_VM107_ROOT)
if _vm107_str not in sys.path:
    sys.path.insert(0, _vm107_str)
elif sys.path[0] != _vm107_str:
    # Move to front in case it was added later by a conftest.py
    sys.path.remove(_vm107_str)
    sys.path.insert(0, _vm107_str)

# Also add FinGPT parent so `VM107.*` package imports resolve.
# (VM107/__init__.py is intentionally absent — VM107 is treated as a namespace
#  package when imported from the parent directory.)
_fingpt_str = str(_FINGPT_ROOT)
if _fingpt_str not in sys.path:
    sys.path.insert(1, _fingpt_str)

# Clear any cached `tools` namespace package from site-packages that would
# shadow VM107/tools/. Python caches the first finder result; we need the
# VM107 version. Removing the cache entry forces re-resolution on next import.
for key in list(sys.modules.keys()):
    if key == "tools" or key.startswith("tools."):
        del sys.modules[key]


def pytest_configure(config):
    """Ensure VM107 root stays at front of sys.path throughout the session."""
    _root = Path(__file__).resolve().parent
    _vm107 = str(_root)
    _fingpt = str(_root.parent)

    if _vm107 not in sys.path:
        sys.path.insert(0, _vm107)
    elif sys.path[0] != _vm107:
        sys.path.remove(_vm107)
        sys.path.insert(0, _vm107)

    # Also ensure FinGPT parent for VM107.* package imports
    if _fingpt not in sys.path:
        sys.path.insert(1, _fingpt)

    # Re-clear stale tools namespace cache
    for key in list(sys.modules.keys()):
        if key == "tools" or key.startswith("tools."):
            del sys.modules[key]
