"""SC-3 gate — zero literal-IP FALLBACK DEFAULTS in VM107 runtime code.

P4 / D-04: runtime config must be fail-fast env-driven; a literal-IP fallback
default silently points the runtime at a hardcoded host and is forbidden. Commit
``3b5657a`` already removed the last one from the memory plugin, so THIS gate is
GREEN today — it is a REGRESSION LOCK, the one SC that ships green from the start.

The two forbidden syntactic shapes (dotted-quad literal only)::

    os.environ.get("KEY", "192.168.1.151")     # fallback default
    SOME_VAR = "192.168.1.151"                  # bare literal assignment

Deliberately NOT flagged (per plan scope):
  * ``/tests/``, ``/scripts/`` and ``conftest*`` files (D-04 = runtime code only)
  * comment / docstring ``e.g.`` IP examples and dict-literal ``"key": "ip"`` pairs
    (e.g. ``factory.py``'s docstring ``"qdrant_host": "192.168.1.151"``) — a
    ``KEY: "ip"`` pair is neither of the two assignment shapes
  * the ``0.0.0.0`` bind wildcard (``mcpserver/server.py``) — a bind address,
    never a fallback target

``test_negative_control_regex_bites_forbidden_shapes`` proves the regexes DO bite
the forbidden shapes, so a future regression
(``os.environ.get("QDRANT_HOST", "192.168.1.151")``) would flip this gate RED —
guarding against a vacuously-passing over-narrow gate.
"""
from __future__ import annotations

import re
from pathlib import Path

# VM107 repo root: phase136 -> tests -> <root>
_REPO_ROOT = Path(__file__).resolve().parents[2]

# A dotted-quad, so "1.0" / "6333" / version strings never match.
_DOTTED_QUAD = r"(?:\d{1,3}\.){3}\d{1,3}"

# Shape 1: os.environ.get(KEY, "<dotted-quad>")  — fallback default.
_SHAPE_GET = re.compile(
    r"""os\.environ\.get\(\s*[^,]+,\s*['"](?P<ip>""" + _DOTTED_QUAD + r""")['"]"""
)
# Shape 2: IDENT = "<dotted-quad>"  — bare literal assignment (indent-anchored so
# dict pairs `"key": "ip"` and comparisons never match).
_SHAPE_ASSIGN = re.compile(
    r"""^\s*[A-Za-z_][A-Za-z0-9_]*\s*=\s*['"](?P<ip>""" + _DOTTED_QUAD + r""")['"]"""
)

# Bind wildcard — a bind address, never a fallback target (explicitly allowed).
_ALLOWED_IPS = {"0.0.0.0"}

_EXCLUDE_DIR_PARTS = {
    "tests",
    "scripts",
    "__pycache__",
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "site-packages",
    ".pytest_cache",
}


def _runtime_py_files():
    for path in _REPO_ROOT.rglob("*.py"):
        if set(path.parts) & _EXCLUDE_DIR_PARTS:
            continue
        if path.name.startswith("conftest"):
            continue
        yield path


def _scan_line(line: str):
    """Return the offending IP literal on this line, or ``None``. Skips comments."""
    if line.lstrip().startswith("#"):
        return None
    for rx in (_SHAPE_GET, _SHAPE_ASSIGN):
        m = rx.search(line)
        if m and m.group("ip") not in _ALLOWED_IPS:
            return m.group("ip")
    return None


def test_no_literal_ip_fallback_defaults_in_runtime_code():
    """SC-3 gate (GREEN regression lock): the runtime kill-list must be empty."""
    offenders = []
    for path in _runtime_py_files():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            ip = _scan_line(line)
            if ip is not None:
                rel = path.relative_to(_REPO_ROOT)
                offenders.append(f"{rel}:{i}: {ip}  |  {line.strip()}")
    assert offenders == [], (
        "SC-3 REGRESSION: literal-IP fallback default(s) reintroduced into runtime "
        "code (D-04 forbids them — use fail-fast os.environ[...]):\n  "
        + "\n  ".join(offenders)
    )


def test_negative_control_regex_bites_forbidden_shapes():
    """Prove the gate would FAIL if a literal-IP default were reintroduced.

    Without this, an over-narrow regex could pass the gate vacuously.
    """
    # The forbidden shapes MUST be caught:
    assert (
        _scan_line('    QDRANT_HOST = os.environ.get("QDRANT_HOST", "192.168.1.151")')
        == "192.168.1.151"
    )
    assert _scan_line('QDRANT_HOST = "192.168.1.151"') == "192.168.1.151"

    # The deliberate non-targets MUST NOT trip it:
    assert _scan_line('    host="0.0.0.0",') is None  # bind wildcard allowed
    assert _scan_line('    "qdrant_host": "192.168.1.151",') is None  # dict-literal pair
    assert _scan_line("    # e.g. QDRANT_HOST=192.168.1.151") is None  # comment example
    assert (
        _scan_line('INTERRUPT_POLL_SEC = os.environ.get("X", "1.0")') is None
    )  # not a dotted-quad
