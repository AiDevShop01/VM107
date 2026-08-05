"""Phase 135 (D4) — CodeExecution must not crash when self.log was never set.

A denied/misinvoked code_execution_tool runs `execute()` / its output helpers WITHOUT
`before_execution()` having set `self.log`. Before the D4-01 fix, `Tool.__init__` never
sets `self.log`, so the first `self.log.update(...)` raises
`AttributeError: 'CodeExecution' object has no attribute 'log'` — an opaque internal crash
instead of a clean refusal (SC-3 / T-135-04).

This test constructs a `CodeExecution` WITHOUT `before_execution` and asserts:
  (1) `self.log is None` post-construction — the D4-01 additive default in `Tool.__init__`
      (not a missing attribute), and
  (2) driving a code path that reaches a `self.log.update(...)` site returns a clean
      string/Response with NO `AttributeError` — the 9 `if self.log:` guards in
      `code_execution_tool.py`.

RED until 135-04 Task 2 lands (`self.log = None` default + the 9 guards). Today,
`ce.log` raises AttributeError (attribute never set) and the `self.log.update` site crashes.

Scope note (D4-02, out of scope): this is the DEFENSIVE guard only — it does NOT chase
*why* a denied tool is constructed without `log` (that is Phase 137 / P5).
"""
import asyncio
import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from plugins._code_execution.tools.code_execution_tool import CodeExecution  # noqa: E402


class _StubAgent:
    """Minimal agent surface `CodeExecution.reset_terminal` touches once prepare_state
    is stubbed. `read_prompt` is the only method reached; it returns a canned string so
    the test can assert a clean, non-crashing outcome without a live agent/context/log.
    """

    def read_prompt(self, *args, **kwargs):
        return "terminal reset"


def _make_code_execution() -> CodeExecution:
    """Construct a CodeExecution via the base `Tool` constructor WITHOUT before_execution,
    so `self.log` stays at its constructor default (None after the fix; unset before)."""
    return CodeExecution(
        agent=_StubAgent(),
        name="code_execution_tool",
        method=None,
        args={},
        message="",
        loop_data=None,
    )


def test_log_is_none_after_construction_without_before_execution():
    """D4-01 additive default: `self.log is None` — not a missing attribute.

    RED today: accessing `ce.log` raises AttributeError (Tool.__init__ never sets it).
    """
    ce = _make_code_execution()
    assert ce.log is None


def test_log_update_site_does_not_crash_when_log_is_none():
    """A `self.log.update(...)` site short-circuits cleanly when `self.log` is None.

    Drives `reset_terminal`, which reaches `self.log.update(content=response)` (line ~426).
    The deep `prepare_state` (shell/context) is stubbed to a no-op so the test isolates the
    guard; with `self.log` None and the `if self.log:` guard the call must return the
    response string, NOT raise `AttributeError`.

    RED today: the unguarded `self.log.update(...)` raises AttributeError.
    """
    ce = _make_code_execution()

    async def _noop_prepare_state(cfg, reset=False, session=None):
        return None

    ce.prepare_state = _noop_prepare_state

    result = asyncio.run(ce.reset_terminal({}, session=0))
    assert result == "terminal reset"
