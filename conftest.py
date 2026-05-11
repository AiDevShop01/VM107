"""VM107 root conftest — ensures VM107 root is in sys.path for all tests.

This conftest runs before pytest collects any test, so the VM107 tools
package is importable as `tools.xxx` in all test files regardless of
which directory pytest starts collecting from first.

Also clears any namespace-package `tools` entry that Python may have
cached from site-packages before VM107 was injected (avoids shadowing).
"""
from __future__ import annotations

import sys
from pathlib import Path

_VM107_ROOT = Path(__file__).resolve().parent

# Ensure VM107 root is at the FRONT of sys.path so `tools.*` resolves
# to VM107/tools/ before any site-packages namespace package.
_vm107_str = str(_VM107_ROOT)
if _vm107_str not in sys.path:
    sys.path.insert(0, _vm107_str)
elif sys.path[0] != _vm107_str:
    # Move to front in case it was added later by a conftest.py
    sys.path.remove(_vm107_str)
    sys.path.insert(0, _vm107_str)

# Clear any cached `tools` namespace package from site-packages that would
# shadow VM107/tools/. Python caches the first finder result; we need the
# VM107 version. Removing the cache entry forces re-resolution on next import.
for key in list(sys.modules.keys()):
    if key == "tools" or key.startswith("tools."):
        del sys.modules[key]


def pytest_configure(config):
    """Ensure VM107 root stays at front of sys.path throughout the session."""
    _vm107 = str(Path(__file__).resolve().parent)
    if _vm107 not in sys.path:
        sys.path.insert(0, _vm107)
    elif sys.path[0] != _vm107:
        sys.path.remove(_vm107)
        sys.path.insert(0, _vm107)
    # Re-clear stale tools namespace cache
    for key in list(sys.modules.keys()):
        if key == "tools" or key.startswith("tools."):
            del sys.modules[key]
