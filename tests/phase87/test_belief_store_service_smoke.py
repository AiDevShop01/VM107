"""Smoke tests for BeliefStore class — env-driven fail-fast + module wiring.

Phase 87 Wave 5 — Task 2. Full integration coverage (Postgres + Mongo round-trips)
lives in Wave 8 deploy gate against the real dev DB; these checks pin the
construction-time contract that catches regressions in CI.
"""
import os

import pytest

pytestmark = pytest.mark.phase_87


def test_belief_store_importable():
    """BeliefStore module loads and exports the expected name."""
    from VM107.core.belief.belief_store import BeliefStore  # noqa: F401
    assert BeliefStore is not None


def test_belief_store_fail_fast_no_postgres_url(monkeypatch):
    from VM107.core.belief.belief_store import BeliefStore

    monkeypatch.delenv("BELIEF_STORE_POSTGRES_URL", raising=False)
    monkeypatch.delenv("BELIEF_STORE_MONGO_URL", raising=False)
    with pytest.raises(RuntimeError, match="BELIEF_STORE_POSTGRES_URL required"):
        BeliefStore()


def test_belief_store_fail_fast_no_mongo_url(monkeypatch):
    from VM107.core.belief.belief_store import BeliefStore

    # Postgres URL present; Mongo missing → still fails fast on Mongo
    monkeypatch.setenv("BELIEF_STORE_POSTGRES_URL", "postgresql://x:y@127.0.0.1:1/z")
    monkeypatch.delenv("BELIEF_STORE_MONGO_URL", raising=False)
    with pytest.raises(RuntimeError, match="BELIEF_STORE_MONGO_URL required"):
        BeliefStore()


def test_no_env_default_fallbacks_in_source():
    """Project lock — no `os.getenv(..., 'default')` fallbacks in belief code."""
    import pathlib
    src_dir = pathlib.Path(__file__).resolve().parents[2] / "core" / "belief"
    for py in src_dir.glob("*.py"):
        body = py.read_text()
        # the only allowed `os.getenv` calls are no-default lookups
        if "os.getenv" in body:
            # crude: assert there is no `, ` after the URL var name in a getenv call
            assert ', "' not in body.split("os.getenv")[1].split(")")[0], (
                f"{py.name} contains os.getenv default fallback — env-driven lock"
            )
        # also fail if os.environ.get is used with a default
        for line in body.splitlines():
            if "os.environ.get" in line:
                # whitelist: single-arg form is fine
                # `os.environ.get(X)` OK; `os.environ.get(X, default)` NOT OK
                # crude split on commas inside parens
                arg_section = line.split("os.environ.get(")[1].split(")")[0]
                assert "," not in arg_section, (
                    f"{py.name} line `{line.strip()}` uses os.environ.get default "
                    "— env-driven lock forbids fallback URLs"
                )
