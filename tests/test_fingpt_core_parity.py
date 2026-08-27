"""Phase 168 (D-05) — fingpt_core cross-copy byte-parity gate.

Contract drift across the vendored `fingpt_core` copies serves *mismatched* contracts
to different VMs (T-168-01). This gate makes that drift a hard test failure. It is the
filesystem gate; the baked VM100/101/102 image rebuilds + VM107 restart are the manual
cross-VM propagation step (VALIDATION Manual-Only) that lands the field in-container.

Two dimensions (per PATTERNS CRITICAL CORRECTION):

1. **_pkg 4-copy byte-gate** — `tool_envelope.py`, `evidence_pack.py`, and
   `invocation_context.py` must be byte-identical across the canonical
   `Dagster/fingpt_core` tree and the three `VM10{0,1,2}/backend/fingpt_core_pkg`
   mirrors. `invocation_context.py` is included as the UNEDITED baseline so 168-07's
   lockstep field-add inherits this live gate (a drift there fails immediately).

2. **events.py 5-copy byte-gate** — `economic_intelligence/events.py` adds a fifth
   surface: the VM107-local vendored copy at `VM107/contracts/economic_intelligence/`.
   All five must be byte-identical.

Plus schema-version constant equality across copies, and a fail-on-injected-drift test
proving the gate actually bites.

Byte-only (mirrors T-139-13/14): the checker reads bytes and parses text; it never
imports or executes either tree, so it is stdlib-only and host-clean (no venv, no
`requires_deps` marker). The `shutil.copytree`-to-tmp discipline (never mutate the repo
tree — fragile-tree rule) is mandatory for the drift-injection test.
"""

from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path

# --- Path resolution (repo-root relative, NOT the runtime bind mount) ------------
# This test lives at <repo-root>/VM107/tests/test_fingpt_core_parity.py, so:
#   parents[0] = tests/  parents[1] = VM107/  parents[2] = <repo-root>
_TEST = Path(__file__).resolve()
REPO_ROOT = _TEST.parents[2]

CANONICAL_CONTRACTS = (
    REPO_ROOT / "Dagster" / "fingpt_core" / "src" / "fingpt_core" / "contracts"
)
PKG_MIRROR_CONTRACTS = [
    REPO_ROOT / vm / "backend" / "fingpt_core_pkg" / "src" / "fingpt_core" / "contracts"
    for vm in ("VM100", "VM101", "VM102")
]
VM107_VENDORED_EVENTS = (
    REPO_ROOT / "VM107" / "contracts" / "economic_intelligence" / "events.py"
)

# Files that live in ALL FOUR _pkg-tier trees (canonical + 3 mirrors).
PKG_PARITY_FILES = [
    "tool_envelope.py",
    "evidence_pack.py",
    "invocation_context.py",  # UNEDITED baseline — 168-07 inherits this live gate
]
# events.py has a fifth surface (VM107 vendored) — handled separately.
EVENTS_REL = "economic_intelligence/events.py"


def _sha256(path: Path) -> str | None:
    """Return the hex sha256 of a file's bytes, or None if it does not exist.

    Reads bytes only — never imports or executes the file.
    """
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def mismatched_copies(reference: Path, copies: list[Path]) -> list[str]:
    """Return the string paths of `copies` whose bytes differ from `reference`.

    A copy mismatches when its sha256 differs from the reference, or when either the
    reference or the copy is absent. Paths only — never file contents.
    """
    ref_hash = _sha256(reference)
    out: list[str] = []
    for c in copies:
        if ref_hash is None or _sha256(c) != ref_hash:
            out.append(str(c))
    return out


def _events_copies() -> list[Path]:
    """The four non-canonical events.py surfaces (3 _pkg mirrors + VM107 vendored)."""
    return [d / EVENTS_REL for d in PKG_MIRROR_CONTRACTS] + [VM107_VENDORED_EVENTS]


def _parse_str_constant(path: Path, name: str) -> str | None:
    """Extract a module-level `NAME: str = "value"` string constant via text parse."""
    text = path.read_text()
    m = re.search(rf'^{re.escape(name)}\s*:\s*str\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return m.group(1) if m else None


def _parse_events_schema_version(path: Path) -> str | None:
    """Extract the `schema_version: str = Field(default="X"...)` default from events.py."""
    text = path.read_text()
    m = re.search(r'schema_version\s*:\s*str\s*=\s*Field\(\s*default="([^"]+)"', text)
    return m.group(1) if m else None


# --------------------------------------------------------------------------------
# Dimension 1 — _pkg 4-copy byte parity
# --------------------------------------------------------------------------------


def test_pkg_mirror_byte_parity():
    """tool_envelope / evidence_pack / invocation_context byte-identical, 4 copies."""
    all_mismatches: list[str] = []
    for name in PKG_PARITY_FILES:
        reference = CANONICAL_CONTRACTS / name
        assert reference.is_file(), f"canonical file missing: {reference}"
        copies = [d / name for d in PKG_MIRROR_CONTRACTS]
        all_mismatches += mismatched_copies(reference, copies)
    assert all_mismatches == [], (
        "fingpt_core _pkg contract drift detected (rebuild/re-vendor the drifted "
        f"copies from Dagster/fingpt_core): {all_mismatches}"
    )


def test_invocation_context_is_in_parity_set():
    """invocation_context.py is gated as the unedited baseline so 168-07 inherits it."""
    assert "invocation_context.py" in PKG_PARITY_FILES


# --------------------------------------------------------------------------------
# Dimension 2 — events.py 5-copy byte parity
# --------------------------------------------------------------------------------


def test_events_five_copy_byte_parity():
    """economic_intelligence/events.py byte-identical across all FIVE copies."""
    reference = CANONICAL_CONTRACTS / EVENTS_REL
    assert reference.is_file(), f"canonical events.py missing: {reference}"
    mismatches = mismatched_copies(reference, _events_copies())
    assert mismatches == [], (
        f"events.py drift across the 5-copy surface: {mismatches}"
    )


# --------------------------------------------------------------------------------
# Schema-version constant equality (+ expected values)
# --------------------------------------------------------------------------------


def test_schema_version_constants_match_across_copies():
    """ENVELOPE / EVIDENCE_PACK / events schema versions agree across all copies."""
    # ENVELOPE_SCHEMA_VERSION across the 4 tool_envelope copies == "1.1"
    env_paths = [CANONICAL_CONTRACTS / "tool_envelope.py"] + [
        d / "tool_envelope.py" for d in PKG_MIRROR_CONTRACTS
    ]
    env_versions = {_parse_str_constant(p, "ENVELOPE_SCHEMA_VERSION") for p in env_paths}
    assert env_versions == {"1.1"}, f"ENVELOPE_SCHEMA_VERSION mismatch: {env_versions}"

    # EVIDENCE_PACK_SCHEMA_VERSION across the 4 evidence_pack copies == "1.0"
    ep_paths = [CANONICAL_CONTRACTS / "evidence_pack.py"] + [
        d / "evidence_pack.py" for d in PKG_MIRROR_CONTRACTS
    ]
    ep_versions = {
        _parse_str_constant(p, "EVIDENCE_PACK_SCHEMA_VERSION") for p in ep_paths
    }
    assert ep_versions == {"1.0"}, f"EVIDENCE_PACK_SCHEMA_VERSION mismatch: {ep_versions}"

    # events schema_version default across all 5 copies == "2"
    events_paths = [CANONICAL_CONTRACTS / EVENTS_REL] + _events_copies()
    ev_versions = {_parse_events_schema_version(p) for p in events_paths}
    assert ev_versions == {"2"}, f"events schema_version mismatch: {ev_versions}"


# --------------------------------------------------------------------------------
# Fail-on-injected-drift (the gate actually bites)
# --------------------------------------------------------------------------------


def test_parity_fails_on_injected_drift(tmp_path):
    """A one-byte change to a copy is detected as a mismatch (gate bites)."""
    reference = CANONICAL_CONTRACTS / "tool_envelope.py"

    # Copy a mirror into tmp so we never mutate the repo tree.
    clean_copy = tmp_path / "tool_envelope.py"
    shutil.copyfile(PKG_MIRROR_CONTRACTS[0] / "tool_envelope.py", clean_copy)

    # Baseline: the clean tmp copy matches canonical → no mismatch.
    assert mismatched_copies(reference, [clean_copy]) == []

    # Inject a one-byte change → the checker reports the drift.
    clean_copy.write_bytes(clean_copy.read_bytes() + b"#")
    mismatches = mismatched_copies(reference, [clean_copy])
    assert str(clean_copy) in mismatches, (
        "injected one-byte drift was not detected — the parity gate does not bite"
    )


def test_parity_fails_on_missing_copy(tmp_path):
    """A missing copy is reported as drift (coverage cannot silently shrink)."""
    reference = CANONICAL_CONTRACTS / "evidence_pack.py"
    missing = tmp_path / "evidence_pack.py"  # never created
    assert mismatched_copies(reference, [missing]) == [str(missing)]
