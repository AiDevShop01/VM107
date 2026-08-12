#!/usr/bin/env python3
"""Phase 139 (P7 — B-08) — contract-drift gate: sha256 byte-equality vs fingpt_core.

Replaces the manual `vendor …` commit stream with an automated check. The vendored
`contracts/economic_intelligence/*.py` files are byte-mirrors of the upstream
`fingpt_core` source (the vendoring contract is literally byte-equality — see the
docstring in `contracts/economic_intelligence/country.py`). A pydantic schema differ
would miss whitespace/comment drift AND pull the package, so the mechanism is a plain
`hashlib.sha256` byte-diff over an explicit vendored-file manifest: any mismatch →
`sys.exit(1)`, all clean → `sys.exit(0)`.

CI-resolvability (Pitfall 4): the upstream source is resolved via the IN-MONOREPO path
`<repo-root>/Dagster/fingpt_core/src/fingpt_core/contracts/economic_intelligence/`,
NOT the runtime container bind mount. Both the VM107 `contracts/` tree and
`Dagster/fingpt_core` live in the same top-level FinGPT monorepo, so this check needs
only filesystem access — no bind mount, no package install, resolvable in CI.

Security (T-139-13/14): this compares BYTES ONLY. It never imports or executes either
tree, and on drift it prints filenames only — never file contents.

Scope (OQ2): the vendored `economic_intelligence/*.py` byte-diff only. The import-coupled
`core/contracts/{envelope,schemas}.py` modules *import* from fingpt_core rather than
vendoring a byte-copy; their "drift" is import-resolution / re-exported-name existence,
a different mechanism — explicitly OUT OF SCOPE here (noted as an open question).

Companion: tests/regression_p7/test_contract_drift.py — the SC-3 pass-clean +
fail-on-injected-drift acceptance wrapper (F5 suite).

Analog: scripts/check_forbidden_patterns.py (shebang + docstring + MANIFEST constant +
sys.exit idiom).
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

# --- Path resolution (repo-root relative, NOT the runtime bind mount) ------------
# This script lives at <repo-root>/VM107/scripts/check_contract_drift.py, so:
#   parents[0] = scripts/  parents[1] = VM107/  parents[2] = <repo-root>
_SCRIPT = Path(__file__).resolve()
VM107_ROOT = _SCRIPT.parents[1]
REPO_ROOT = _SCRIPT.parents[2]

# Vendored copy (VM107 side) and the in-monorepo upstream source (fingpt_core side).
VENDORED_DIR = VM107_ROOT / "contracts" / "economic_intelligence"
UPSTREAM_DIR = (
    REPO_ROOT
    / "Dagster"
    / "fingpt_core"
    / "src"
    / "fingpt_core"
    / "contracts"
    / "economic_intelligence"
)

# --- Explicit vendored-file manifest --------------------------------------------
# The economic_intelligence/*.py files that are byte-mirrors of fingpt_core. Listed
# explicitly (not glob-discovered) so a deleted/renamed file surfaces as a hard
# missing-file drift rather than silently shrinking the gate's coverage.
MANIFEST: list[str] = [
    "__init__.py",
    "alerts.py",
    "base_section.py",
    "central_bank.py",
    "country.py",
    "country_card.py",
    "country_health_composite.py",
    "country_search.py",
    "country_tab.py",
    "cross_asset.py",
    "domain.py",
    "economic_dna_tag.py",
    "events.py",
    "executive_summary.py",
    "forecast.py",
    "pillars.py",
    "provenance.py",
    "relationships.py",
    "research.py",
    "snapshot.py",
    "specialist_response.py",
    "themes.py",
    "timeline.py",
]


def _sha256(path: Path) -> str | None:
    """Return the hex sha256 of a file's bytes, or None if it does not exist.

    Reads bytes only — never imports or executes the file (T-139-13).
    """
    if not path.is_file():
        return None
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def find_drift(vendored_dir: Path, upstream_dir: Path) -> list[str]:
    """Return the list of manifest filenames whose bytes differ (or are missing).

    A file drifts when the vendored and upstream sha256 differ, or when either copy
    is absent. Filenames only — no content — so callers/logs never leak file bodies
    (T-139-14). Pure byte comparison; neither tree is imported (T-139-13).
    """
    mismatches: list[str] = []
    for name in MANIFEST:
        vendored_hash = _sha256(vendored_dir / name)
        upstream_hash = _sha256(upstream_dir / name)
        if vendored_hash is None or upstream_hash is None or vendored_hash != upstream_hash:
            mismatches.append(name)
    return mismatches


def main() -> int:
    mismatches = find_drift(VENDORED_DIR, UPSTREAM_DIR)
    if not mismatches:
        print(
            f"contract-drift: OK — {len(MANIFEST)} vendored "
            "economic_intelligence/*.py files byte-identical to fingpt_core."
        )
        return 0

    print(
        "ERROR: contract drift detected — vendored economic_intelligence/*.py "
        "differs from Dagster/fingpt_core source:",
        file=sys.stderr,
    )
    for name in mismatches:
        # Filenames only, never contents (T-139-14).
        print(f"  DRIFT: contracts/economic_intelligence/{name}", file=sys.stderr)
    print(
        "\nRe-vendor the drifted file(s) from "
        "Dagster/fingpt_core/src/fingpt_core/contracts/economic_intelligence/ "
        "(byte-equality is the vendoring contract).",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
