"""Phase 156 — test env for the domain_analyst_subscriber suite.

``domain_fetcher.py`` reads ``VM100_API_URL`` and ``VM107_SERVICE_JWT`` at
import time (fail-fast, no defaults — CLAUDE.md env-driven-config lock). The
CI host does not export them, so set harmless test placeholders here *before*
the fetcher module is imported. Mirrors ``tests/phase83/conftest.py``.

``setdefault`` (not ``[...] =``) so a real environment that already exports
these is never clobbered, and the fail-fast import path stays exercised in
production.
"""
from __future__ import annotations

import os

os.environ.setdefault("VM100_API_URL", "http://test-vm100.local:8000")
os.environ.setdefault("VM107_SERVICE_JWT", "test-jwt-not-real")
