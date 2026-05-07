"""Phase 47.2.1 — CI grep test asserting Polars is GONE from VM107.

Plan 47.2.1-05 Task 2 graduated this from xfail to a regular GREEN regression
guard. The xfail decorator that previously sat at module level has been
removed; future phases must not re-introduce Polars into VM107/tools/ or
VM107/core/.

Specs (3):
- test_no_import_polars_in_tools  — AST walk over VM107/tools/*.py
- test_no_import_polars_in_core   — AST walk over VM107/core/*.py
- test_polars_not_in_requirements — grep VM107/requirements.txt
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest


_VM107_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _has_polars_import(path: pathlib.Path) -> bool:
    """AST-walk a Python file checking for any Polars import.

    Handles all forms:
      import polars
      import polars as pl
      from polars import DataFrame
      from polars.frames import LazyFrame
    """
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "polars" or alias.name.startswith("polars."):
                    return True
        elif isinstance(node, ast.ImportFrom):
            if node.module and (node.module == "polars" or node.module.startswith("polars.")):
                return True
    return False


def _walk_py(root: pathlib.Path) -> list[pathlib.Path]:
    if not root.exists():
        return []
    return [
        p
        for p in root.rglob("*.py")
        if "__pycache__" not in str(p) and ".pytest_cache" not in str(p)
    ]


def test_no_import_polars_in_tools():
    """No file under VM107/tools/ may import Polars."""
    offenders = []
    for p in _walk_py(_VM107_ROOT / "tools"):
        if _has_polars_import(p):
            offenders.append(str(p.relative_to(_VM107_ROOT)))
    assert not offenders, f"Polars still imported in VM107/tools: {offenders}"


def test_no_import_polars_in_core():
    """No file under VM107/core/ may import Polars."""
    offenders = []
    for p in _walk_py(_VM107_ROOT / "core"):
        if _has_polars_import(p):
            offenders.append(str(p.relative_to(_VM107_ROOT)))
    assert not offenders, f"Polars still imported in VM107/core: {offenders}"


def test_polars_not_in_requirements():
    """VM107/requirements.txt must NOT pin polars."""
    req = _VM107_ROOT / "requirements.txt"
    if not req.exists():
        pytest.skip("VM107/requirements.txt not present")
    pin_re = re.compile(r"^\s*polars[\s>=<~!]", re.IGNORECASE | re.MULTILINE)
    offenders = pin_re.findall(req.read_text())
    assert not offenders, f"polars pin still in requirements.txt: {offenders}"
