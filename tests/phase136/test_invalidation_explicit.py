"""SC-2 gate — mission_control invalidation is EXPLICIT, never a silent no-op.

Two halves, both RED at develop HEAD:

  (a) DI publish contract — ``SnapshotInvalidationPublisher(redis_client=fake)``
      ``.publish_after_commit(...)`` must fire exactly ONE decoupled Redis publish
      to ``mission_control_{account_id}_{topic}`` carrying the thin payload
      ``{topic, snapshot_id, generated_at, invalidation_reason}``. RED until 136-02
      creates ``services/snapshot_invalidation_publisher.py`` (import guarded in the
      test body so this file COLLECTS at HEAD, failing on ``pytest.fail`` not on a
      collection-time ImportError).

  (b) STATIC no-silent-swallow — the 5 emitter dead-path sites must contain ZERO
      ``except ImportError:`` blocks whose body is a bare ``return`` with no
      ``log.`` line (Pitfall 1 / Anti-Pattern: the Django-guard early-return that
      no-ops BEFORE the publisher import). RED at HEAD — 4 emitters still carry the
      silent Django guard.

Verified topic map: global_narrative->homepage.global,
morning_brief->mission_control.pre.morning_brief,
overnight_delta->mission_control.pre.overnight_delta,
reflection_prompt->mission_control.close.journal_prompts,
opportunity_ranker->mission_control.opportunities.
``scoring_primitives.py`` is NOT a publisher site (CONTEXT mislabel) — excluded.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_EMITTER_DIR = _REPO_ROOT / "emitters"

# The 5 real invalidation dead-path sites (scoring_primitives.py excluded — not a site).
_EMITTER_FILES = [
    _EMITTER_DIR / "global_narrative_emitter.py",
    _EMITTER_DIR / "morning_brief_emitter.py",
    _EMITTER_DIR / "overnight_delta_emitter.py",
    _EMITTER_DIR / "reflection_prompt_emitter.py",
    _EMITTER_DIR / "opportunity_ranker.py",
]


# ── (a) DI publish contract ────────────────────────────────────────────────


def test_publisher_fires_decoupled_redis_publish(fake_redis):
    """SC-2(a): the local publisher fires one thin-payload Redis publish (RED until 136-02)."""
    try:
        from services.snapshot_invalidation_publisher import (
            SnapshotInvalidationPublisher,
        )
    except ImportError as exc:
        pytest.fail(
            "RED (expected until 136-02): services.snapshot_invalidation_publisher "
            f"is absent — {type(exc).__name__}. This gate turns GREEN when the "
            "Django-free VM107 publisher lands."
        )

    publisher = SnapshotInvalidationPublisher(redis_client=fake_redis)
    publisher.publish_after_commit(
        topic="homepage.global", snapshot_id="s1", account_id=42
    )

    assert len(fake_redis.published) == 1, (
        f"expected exactly one decoupled publish, got {len(fake_redis.published)}"
    )
    channel, raw = fake_redis.published[0]
    assert channel == "mission_control_42_homepage.global", (
        f"channel convention mismatch: {channel!r}"
    )
    payload = json.loads(raw)
    assert set(payload) >= {
        "topic",
        "snapshot_id",
        "generated_at",
        "invalidation_reason",
    }, f"thin payload missing keys: got {sorted(payload)}"
    assert payload["topic"] == "homepage.global"
    assert payload["snapshot_id"] == "s1"
    assert payload["invalidation_reason"] == "SCHEDULED"  # default per contract


# ── (b) STATIC no-silent-swallow ──────────────────────────────────────────


def _handler_catches_import_error(handler: ast.ExceptHandler) -> bool:
    t = handler.type
    if t is None:
        return False  # bare `except:` is a different shape — not the Django guard
    names = []
    if isinstance(t, ast.Name):
        names = [t.id]
    elif isinstance(t, ast.Tuple):
        names = [e.id for e in t.elts if isinstance(e, ast.Name)]
    return "ImportError" in names


def _handler_has_log_call(handler: ast.ExceptHandler) -> bool:
    for node in ast.walk(handler):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            # e.g. log.warning(...), logger.info(...), self.log.warning(...)
            if node.func.attr in {
                "debug",
                "info",
                "warning",
                "warn",
                "error",
                "exception",
                "critical",
            }:
                return True
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
        ):
            return True
    return False


def _handler_has_top_level_return(handler: ast.ExceptHandler) -> bool:
    # A `return` directly in the handler body (not nested inside a further try/func).
    return any(isinstance(node, ast.Return) for node in handler.body)


def _find_silent_swallows(source: str):
    """Return [lineno, ...] for ImportError handlers that `return` with no log call."""
    offenders = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ExceptHandler) and _handler_catches_import_error(node):
            if _handler_has_top_level_return(node) and not _handler_has_log_call(node):
                offenders.append(node.lineno)
    return offenders


def test_no_silent_swallow_import_guard_in_emitters():
    """SC-2(b): zero `except ImportError: return` (no-log) blocks across the 5 emitters (RED at HEAD)."""
    all_offenders = []
    for path in _EMITTER_FILES:
        assert path.exists(), f"emitter site missing: {path}"
        source = path.read_text(encoding="utf-8", errors="replace")
        for lineno in _find_silent_swallows(source):
            all_offenders.append(f"{path.relative_to(_REPO_ROOT)}:{lineno}")
    assert all_offenders == [], (
        "SC-2 not met: silent-swallow `except ImportError: return` (no log) still "
        "present — the Django-guard early-return no-ops BEFORE the publisher import "
        "(Pitfall 1). Restructure to an explicit publish attempt or a WARN/INFO "
        "no-op:\n  " + "\n  ".join(all_offenders)
    )


def test_each_emitter_reaches_a_publish_attempt():
    """Every one of the 5 sites must reference the publish contract (call surface intact)."""
    for path in _EMITTER_FILES:
        source = path.read_text(encoding="utf-8", errors="replace")
        assert "publish_after_commit" in source, (
            f"{path.relative_to(_REPO_ROOT)} no longer references publish_after_commit — "
            "the invalidation call contract must remain"
        )
