#!/usr/bin/env python3
"""Phase 48 Wave 0 — materialize pytest stubs from declarative manifest.

Reads VM107/tests/_phase48_stubs_manifest.yaml and writes a `pytest.skip`
stub to every listed path. Idempotent — files that already exist on disk
are skipped, never overwritten.

Run from VM107/:
    python tests/_phase48_generate_stubs.py

Outputs a final summary line of the form:
    Phase 48 stub generation: created=<N>, skipped=<M>
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent  # VM107/
MANIFEST = ROOT / "tests" / "_phase48_stubs_manifest.yaml"

STUB_TEMPLATE_SYNC = '''"""TODO Phase 48 Plan {plan} — {req}.

Stub created by Plan 00 / Wave 0 via tests/_phase48_generate_stubs.py.
Real implementation lands in Plan {plan}. See:
  .planning/phases/48-idea-to-strategy-to-code-pipeline/48-VALIDATION.md
"""
import pytest


def test_placeholder_will_fail() -> None:
    pytest.skip(
        "Stub created in Plan 00 / Wave 0; implementation lands in Plan {plan}"
    )
'''

STUB_TEMPLATE_ASYNC = '''"""TODO Phase 48 Plan {plan} — {req}.

Stub created by Plan 00 / Wave 0 via tests/_phase48_generate_stubs.py.
Real implementation lands in Plan {plan}. See:
  .planning/phases/48-idea-to-strategy-to-code-pipeline/48-VALIDATION.md
"""
import pytest


@pytest.mark.asyncio
async def test_placeholder_will_fail() -> None:
    pytest.skip(
        "Stub created in Plan 00 / Wave 0; implementation lands in Plan {plan}"
    )
'''


def main() -> int:
    if not MANIFEST.exists():
        print(f"ERROR: manifest not found at {MANIFEST}", file=sys.stderr)
        return 1

    data = yaml.safe_load(MANIFEST.read_text())
    if not data or "stubs" not in data:
        print("ERROR: manifest has no 'stubs' key", file=sys.stderr)
        return 1

    created = 0
    skipped = 0

    for entry in data["stubs"]:
        rel_path = entry["path"]
        path = ROOT / rel_path
        if path.exists():
            skipped += 1
            continue

        path.parent.mkdir(parents=True, exist_ok=True)

        # Ensure every test directory along the path has __init__.py for
        # pytest collection (idempotent — won't overwrite existing inits).
        pkg = path.parent
        tests_root = ROOT / "tests"
        while pkg.is_relative_to(tests_root) or pkg == tests_root:
            init = pkg / "__init__.py"
            if not init.exists():
                init.write_text("")
            if pkg == tests_root:
                break
            pkg = pkg.parent

        tpl = STUB_TEMPLATE_ASYNC if entry.get("async") else STUB_TEMPLATE_SYNC
        body = tpl.format(plan=entry["plan"], req=entry["req"])
        path.write_text(body)
        created += 1

    print(f"Phase 48 stub generation: created={created}, skipped={skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
