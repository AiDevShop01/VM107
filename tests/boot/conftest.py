"""Phase 132 Plan 01 — Wave 0 boot-reliability test bootstrap.

Ensures the VM107 repo root is importable so the boot tests can lazily import
app modules (helpers.defer, helpers.server_startup, helpers.mcp_handler, and the
docker/run/fs/exe/self_update_manager.py bootstrap) from inside their test bodies.

Mirrors the sys.path bootstrap idiom in tests/boot/test_hard_fail.py so collection
never errors even while the Wave 1-2 wiring (InitTimeout, watchdog cancel, normal-path
health-gate) is not yet landed and the assertions stay RED.
"""
from __future__ import annotations

import sys
from pathlib import Path

# tests/boot/conftest.py -> parent(boot) -> parent(tests) -> parent(VM107 root)
_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))
