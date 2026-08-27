"""Shared fixtures for the agent-catalogue governance tests (Phase 167 Wave 0).

Standalone: pyyaml only. Mirrors the ``tests/registry/fixtures/`` convention with a
static ``fixtures/`` corpus (profiles + catalogue) plus tmp-dir factory fixtures for
building isolated custom scenarios (clean corpus, malformed frontmatter).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import yaml

# Ensure VM107 root is on sys.path so `import scripts.agent_contract_lint` resolves.
_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

# Some VM107 import paths expect these env vars; set benign test defaults.
os.environ.setdefault("VM100_INTERNAL_BASE_URL", "http://test-vm100:8000")
os.environ.setdefault("SCOPE_DISPATCHER_SECRET_KEY", "test-secret")

_FIXTURES = Path(__file__).parent / "fixtures"

# The 14 numbered Contract section titles (mirrors agent-catalogue/_TEMPLATE.md §3).
SECTION_TITLES = [
    "Mission",
    "Responsibilities",
    "Non-responsibilities",
    "Trigger model",
    "Inputs",
    "Tools",
    "Memory",
    "Reasoning outputs",
    "Confidence & evidence",
    "Authority",
    "Collaboration",
    "Lifecycle",
    "Failure behaviour",
    "Evaluation",
]


def _valid_body(tools: list[str]) -> str:
    """A complete 14-section Contract body, with §6 listing ``tools``."""
    lines: list[str] = ["# Agent", ""]
    for n, title in enumerate(SECTION_TITLES, start=1):
        lines.append(f"## {n}. {title}")
        if n == 6:
            for t in tools:
                lines.append(f"- `{t}` — purpose.")
        else:
            lines.append("x")
        lines.append("")
    return "\n".join(lines)


@pytest.fixture
def corpus():
    """(profiles_dir, catalogue_dir) for the static fixture corpus.

    Exercises all six fixture shapes: valid pair, orphan profile, missing-field
    catalogue entry, tools/authority disagreement, id-mismatch (canon) pair, and the
    canon-base parent + ``._reader`` sub-profile collapse pair.
    """
    return _FIXTURES / "profiles", _FIXTURES / "catalogue"


@pytest.fixture
def profile_dir(tmp_path):
    d = tmp_path / "agent_profile"
    d.mkdir()
    return d


@pytest.fixture
def catalogue_dir(tmp_path):
    d = tmp_path / "catalogue"
    d.mkdir()
    return d


@pytest.fixture
def write_profile():
    """Write a registry-profile YAML into ``profile_dir``."""
    def _w(profile_dir: Path, filename: str, **fields) -> Path:
        path = profile_dir / filename
        path.write_text(yaml.safe_dump(fields, sort_keys=False))
        return path
    return _w


@pytest.fixture
def write_catalogue():
    """Write a catalogue ``.md`` with frontmatter + a full 14-section body.

    ``tools`` populates §6; pass ``body=`` to override the auto-generated body
    (e.g. to inject malformed content).
    """
    def _w(catalogue_dir: Path, filename: str, frontmatter: dict,
           tools: list[str] | None = None, body: str | None = None) -> Path:
        fm = yaml.safe_dump(frontmatter, sort_keys=False)
        if body is None:
            body = _valid_body(tools or [])
        path = catalogue_dir / filename
        path.write_text(f"---\n{fm}---\n\n{body}")
        return path
    return _w
