"""Phase 85 Plan 01 — Router fail-fast subprocess tests.

REQ-85-7: VM107 macro_* agent boot exits 1 if Redis is unreachable or
REDIS_URL is unset. Tested via subprocess so sys.exit(1) actually terminates
the subprocess without affecting the test runner.
"""
import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.phase_85

# Inline script that imports assert_router_reachable and calls it.
# Subprocess exit code 1 = Redis unreachable/unset; exit code 0 = reachable.
SCRIPT = (
    "import sys; sys.path.insert(0, '.');"
    "from agents._router_reachability import assert_router_reachable;"
    "assert_router_reachable();"
    "print('OK')"
)


def test_router_fail_fast_no_redis_url():
    """Unset REDIS_URL → process must exit with code 1."""
    env = {k: v for k, v in os.environ.items() if k != "REDIS_URL"}
    p = subprocess.run(
        [sys.executable, "-c", SCRIPT],
        env=env,
        capture_output=True,
        cwd="/Volumes/ HardDrive/FinGPT/VM107",
    )
    assert p.returncode == 1, (
        f"Expected exit code 1 (no REDIS_URL), got {p.returncode}. "
        f"stdout={p.stdout!r} stderr={p.stderr!r}"
    )


def test_router_fail_fast_invalid_redis_url():
    """Invalid/unreachable REDIS_URL → process must exit with code 1."""
    env = {**os.environ, "REDIS_URL": "redis://does-not-exist:9999"}
    p = subprocess.run(
        [sys.executable, "-c", SCRIPT],
        env=env,
        capture_output=True,
        timeout=10,
        cwd="/Volumes/ HardDrive/FinGPT/VM107",
    )
    assert p.returncode == 1, (
        f"Expected exit code 1 (bad REDIS_URL), got {p.returncode}. "
        f"stdout={p.stdout!r} stderr={p.stderr!r}"
    )


def test_router_reachable_real_redis():
    """Valid, reachable REDIS_URL → process exits 0 and prints 'OK'.

    Skipped when REDIS_URL is not set in the test environment — this test
    is intended for CI/dev environments where a Redis instance is available.
    """
    if "REDIS_URL" not in os.environ:
        pytest.skip("REDIS_URL not set in test env — skipping live Redis test")
    p = subprocess.run(
        [sys.executable, "-c", SCRIPT],
        env=os.environ.copy(),
        capture_output=True,
        timeout=10,
        cwd="/Volumes/ HardDrive/FinGPT/VM107",
    )
    assert p.returncode == 0, (
        f"Expected exit code 0 (reachable Redis), got {p.returncode}. "
        f"stdout={p.stdout!r} stderr={p.stderr!r}"
    )
    assert b"OK" in p.stdout
