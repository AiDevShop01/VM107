"""Phase 47.2-03 — strategy YAML loader tests (graduated from Wave 0 xfail).

Target module: core.agents.strategy_loader

Covers behavior block of Plan 47.2-03 Task 1:
  - load_strategy("model_2_option_1_short") returns StrategyDefinition
    with id, version=1, 5 criteria, 3 hard_rejects, scoring
  - Always-fresh: edit YAML mid-test, immediately observable on next call (no cache)
  - Missing file: raises StrategyNotFoundError
  - Malformed YAML: raises MalformedStrategyError
  - Schema mismatch: raises MalformedStrategyError
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


def test_load_strategy_returns_strategy_definition():
    """load_strategy('model_2_option_1_short') returns parsed StrategyDefinition.

    The shipped YAML file (`agents/agent0/strategies/model_2_option_1_short.yaml`)
    must satisfy the CONTEXT-locked schema: 5 criteria + 3 hard_rejects + scoring max=7.
    """
    from fingpt_core.contracts.agents.strategy_definition import StrategyDefinition

    from core.agents.strategy_loader import load_strategy

    result = load_strategy("model_2_option_1_short")

    assert isinstance(result, StrategyDefinition)
    assert result.id == "model_2_option_1_short"
    assert result.version == 1
    assert len(result.criteria) == 5
    assert len(result.hard_rejects) == 3
    assert result.scoring is not None
    assert result.scoring.max_score == 7

    # Tri-state required field per CONTEXT lock: 4 true + 1 "preferred"
    required_values = [c.required for c in result.criteria]
    assert required_values.count(True) == 4
    assert required_values.count("preferred") == 1


def test_missing_file_raises_strategy_not_found():
    """load_strategy(unknown_id) raises StrategyNotFoundError."""
    from core.agents.strategy_loader import StrategyNotFoundError, load_strategy

    with pytest.raises(StrategyNotFoundError):
        load_strategy("nonexistent_strategy_xyz_abc")


def test_malformed_yaml_raises_malformed_strategy(tmp_path, monkeypatch):
    """Invalid YAML content raises MalformedStrategyError.

    Patches the loader's strategy directory resolution so we can drop
    a deliberately broken YAML file into a temp dir.
    """
    from core.agents import strategy_loader
    from core.agents.strategy_loader import MalformedStrategyError, load_strategy

    strategies_dir = tmp_path / "strategies"
    strategies_dir.mkdir()
    bad_file = strategies_dir / "bad_yaml.yaml"
    # Unbalanced braces — not parseable
    bad_file.write_text("id: bad_yaml\nversion: 1\ncriteria: [unbalanced\n")

    def fake_get_abs_path(*parts):
        # Last part is the filename; ignore the relative dir argument.
        return str(strategies_dir / parts[-1])

    monkeypatch.setattr(strategy_loader, "get_abs_path", fake_get_abs_path)

    with pytest.raises(MalformedStrategyError):
        load_strategy("bad_yaml")


def test_schema_mismatch_raises_malformed_strategy(tmp_path, monkeypatch):
    """YAML that parses but violates StrategyDefinition schema raises MalformedStrategyError.

    Example: missing required `criteria` and `hard_rejects` fields.
    """
    from core.agents import strategy_loader
    from core.agents.strategy_loader import MalformedStrategyError, load_strategy

    strategies_dir = tmp_path / "strategies"
    strategies_dir.mkdir()
    bad_schema = strategies_dir / "schema_mismatch.yaml"
    bad_schema.write_text(
        textwrap.dedent(
            """\
            id: schema_mismatch
            version: 1
            description: missing criteria + hard_rejects
            """
        )
    )

    def fake_get_abs_path(*parts):
        return str(strategies_dir / parts[-1])

    monkeypatch.setattr(strategy_loader, "get_abs_path", fake_get_abs_path)

    with pytest.raises(MalformedStrategyError):
        load_strategy("schema_mismatch")


def test_id_mismatch_raises_malformed_strategy(tmp_path, monkeypatch):
    """File whose internal `id` doesn't match the requested strategy_id raises MalformedStrategyError."""
    from core.agents import strategy_loader
    from core.agents.strategy_loader import MalformedStrategyError, load_strategy

    strategies_dir = tmp_path / "strategies"
    strategies_dir.mkdir()
    f = strategies_dir / "expected_id.yaml"
    f.write_text(
        textwrap.dedent(
            """\
            id: different_id
            version: 1
            criteria:
              - name: x
                required: true
            hard_rejects:
              - name: y
            """
        )
    )

    def fake_get_abs_path(*parts):
        return str(strategies_dir / parts[-1])

    monkeypatch.setattr(strategy_loader, "get_abs_path", fake_get_abs_path)

    with pytest.raises(MalformedStrategyError):
        load_strategy("expected_id")


def test_always_fresh_no_cache(tmp_path, monkeypatch):
    """Edit YAML between calls; second call sees the new value (no cache).

    CONTEXT.md lock: "editable WITHOUT redeploy". Every call MUST re-read disk.
    """
    from core.agents import strategy_loader
    from core.agents.strategy_loader import load_strategy

    strategies_dir = tmp_path / "strategies"
    strategies_dir.mkdir()

    yaml_path = strategies_dir / "fresh_test.yaml"

    def write_with_version(v: int) -> None:
        yaml_path.write_text(
            textwrap.dedent(
                f"""\
                id: fresh_test
                version: {v}
                description: cache freshness probe
                criteria:
                  - name: c1
                    required: true
                hard_rejects:
                  - name: r1
                """
            )
        )

    def fake_get_abs_path(*parts):
        return str(strategies_dir / parts[-1])

    monkeypatch.setattr(strategy_loader, "get_abs_path", fake_get_abs_path)

    write_with_version(1)
    first = load_strategy("fresh_test")
    assert first.version == 1

    write_with_version(2)
    second = load_strategy("fresh_test")
    assert second.version == 2, "Loader must re-read disk on every call (no cache)"
