"""Wave 0 test scaffold for ScopeDispatcher — CTX-§5.

These tests are Wave 0 scaffolds: the file exists so that downstream plans'
<automated> verify blocks can reference real targets. Test bodies are
implemented in Plan 60-05 when ScopeDispatcher is written.

CTX-§5: ScopeDispatcher signs a ScopeContext JWT and attaches it as the
        X-Agent-Scope header on outbound calls to VM100 narrative endpoints.
"""
from __future__ import annotations

import sys
from pathlib import Path

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

import pytest


def test_jwt_signing():
    """CTX-§5 — ScopeDispatcher signs ScopeContext JWT and attaches X-Agent-Scope header."""
    pytest.skip("Wave 0 scaffold — implementation lands in plan 60-05")
