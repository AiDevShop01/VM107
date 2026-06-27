"""Phase 94-05 — Deterministic evidence accumulation contract.

Per CONTEXT.md §H.3 + LD-90-1, theme strength MUST be computed via
deterministic weighted evidence accumulation — NO LLM, NO randomness.
Same evidence twice → identical strength.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from macro_theme_engine import MacroThemeEngine


def _engine() -> MacroThemeEngine:
    return MacroThemeEngine()


def test_strength_increases_when_evidence_satisfied():
    engine = _engine()
    spec = engine.catalog["inflation_persistence"]
    # Use the first two rules with weights w1 + w2; signal both to fire.
    rules = spec["evidence_rules"][:2]
    evidence_keys = [_rule_signal_key(r) for r in rules]
    expected = sum(r["weight"] for r in rules)
    strength = engine.compute_strength(
        theme_id="inflation_persistence",
        satisfied_rule_signals=evidence_keys,
    )
    assert strength == expected, (
        f"strength {strength} must equal sum of satisfied weights {expected}"
    )


def test_deterministic_repeat_run():
    """Same evidence twice → identical strength."""
    engine = _engine()
    spec = engine.catalog["inflation_persistence"]
    rules = spec["evidence_rules"][:2]
    signals = [_rule_signal_key(r) for r in rules]
    s1 = engine.compute_strength("inflation_persistence", signals)
    s2 = engine.compute_strength("inflation_persistence", signals)
    assert s1 == s2


def test_no_evidence_yields_zero_strength():
    engine = _engine()
    assert engine.compute_strength("inflation_persistence", []) == 0


def test_strength_capped_at_one_hundred():
    engine = _engine()
    spec = engine.catalog["inflation_persistence"]
    # Satisfy every rule; cap is 100.
    all_signals = [_rule_signal_key(r) for r in spec["evidence_rules"]]
    strength = engine.compute_strength("inflation_persistence", all_signals)
    assert 0 <= strength <= 100


def test_no_llm_imports_in_engine_source():
    """§H.3 lock — engine source must not import any LLM client."""
    src = Path(MacroThemeEngine.__module__.replace(".", "/") + ".py")
    if not src.exists():
        # Module might be a package — fall back to inspect.getfile
        import inspect
        src = Path(inspect.getfile(MacroThemeEngine))
    text = src.read_text()
    banned = ("import openai", "import anthropic", "import langchain", "import llamaindex")
    for needle in banned:
        assert needle not in text, f"engine source contains banned import: {needle}"
    # Also AST-walk for suspicious attribute names suggesting LLM use.
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert not node.attr.startswith("llm_"), (
                f"engine source uses LLM-prefixed attribute {node.attr!r}"
            )


def test_theme_ranking_uses_strength_times_confidence():
    """§H.4 — dashboard ranking key is Strength × Confidence (not Strength alone)."""
    engine = _engine()
    themes = [
        {"theme_id": "a", "strength": 50.0, "confidence": 0.9},  # rank = 45
        {"theme_id": "b", "strength": 80.0, "confidence": 0.4},  # rank = 32
        {"theme_id": "c", "strength": 60.0, "confidence": 0.8},  # rank = 48
    ]
    ranked = engine.rank_themes(themes)
    ids = [t["theme_id"] for t in ranked]
    assert ids == ["c", "a", "b"], (
        f"ranking must be by Strength × Confidence; got {ids}"
    )


# ─────────────────────────── helpers ────────────────────────────────────


def _rule_signal_key(rule: dict) -> str:
    """Convert a rule dict to its canonical signal key the engine matches on."""
    for key in ("indicator", "event_type", "forecast"):
        if key in rule:
            return f"{key}:{rule[key]}"
    raise ValueError(f"rule missing trigger key: {rule}")
