"""Phase 87 Wave 1 — Standalone loader for the macro graph seed.

Usage::

    python -m scripts.load_macro_graph_seed --dry-run
    python -m scripts.load_macro_graph_seed --check-schema-first
    python -m scripts.load_macro_graph_seed
    python -m scripts.load_macro_graph_seed --seed-yaml /abs/path/seed.yaml

Env vars required (fail-fast; no `os.getenv("X", "default")` patterns):
    NEO4J_BOLT_URL  — e.g., bolt://192.168.1.105:7687
    NEO4J_USER      — Neo4j auth
    NEO4J_PASSWORD  — Neo4j auth
    VM102_BASE_URL  — e.g., http://192.168.1.102:8000

VM107 is not a Django project; this ships as a `python -m scripts.*`-style CLI
that mirrors `scripts/registry_validate.py` (the existing in-repo CLI pattern).

Exit codes:
    0 — load succeeded (or dry-run completed)
    1 — env var missing, seed file missing, schema check failed, or runtime error
"""
from __future__ import annotations

import argparse
import logging
import os
import pathlib
import sys

# Ensure VM107 root is on sys.path so `services.*` imports resolve
_VM107_ROOT = pathlib.Path(__file__).resolve().parent.parent
_vm107_str = str(_VM107_ROOT)
if _vm107_str not in sys.path:
    sys.path.insert(0, _vm107_str)

import neo4j  # noqa: E402

from services.macro_graph.correlation_augmentation import (  # noqa: E402
    CorrelationAugmenter,
)
from services.macro_graph.loader import MacroGraphLoader  # noqa: E402

logger = logging.getLogger("load_macro_graph_seed")


def _env_required(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        sys.stderr.write(
            f"ERROR: env var {key} required for Phase 87 macro graph loader\n"
        )
        sys.exit(1)
    return val


def _default_seed_path() -> pathlib.Path:
    # VM107/scripts/load_macro_graph_seed.py -> parents[1]=VM107 -> parents[2]=FinGPT
    fingpt_root = pathlib.Path(__file__).resolve().parents[2]
    return fingpt_root / "vm105" / "seeds" / "macro_graph_seed.yaml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Load the Phase 87 macro graph seed into Neo4j (Wave 1)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print Cypher to stdout without writing",
    )
    parser.add_argument(
        "--check-schema-first",
        action="store_true",
        help="Error if Plan 87-02 schema migration is not applied",
    )
    parser.add_argument(
        "--seed-yaml",
        default=str(_default_seed_path()),
        help="Override the seed YAML path (default: vm105/seeds/macro_graph_seed.yaml)",
    )
    args = parser.parse_args(argv)

    seed_path = pathlib.Path(args.seed_yaml)
    if not seed_path.exists():
        sys.stderr.write(f"ERROR: Seed file missing: {seed_path}\n")
        return 1

    vm102_url = _env_required("VM102_BASE_URL")
    augmenter = CorrelationAugmenter(vm102_base_url=vm102_url)

    try:
        if args.dry_run:
            # Dry-run does not touch Neo4j; pass driver=None and rely on
            # MacroGraphLoader honouring the dry_run flag.
            loader = MacroGraphLoader(
                seed_yaml_path=seed_path,
                augmenter=augmenter,
                neo4j_driver=None,
            )
            report = loader.load(dry_run=True, check_schema=False)
            for line in report.cypher_log:
                print(line)
            print(
                f"\n[dry-run] {len(report.cypher_log)} Cypher statements; "
                f"{report.degraded_edges} degraded augmentations"
            )
            return 0

        neo4j_url = _env_required("NEO4J_BOLT_URL")
        neo4j_user = _env_required("NEO4J_USER")
        neo4j_pwd = _env_required("NEO4J_PASSWORD")
        driver = neo4j.GraphDatabase.driver(
            neo4j_url, auth=(neo4j_user, neo4j_pwd)
        )
        try:
            loader = MacroGraphLoader(
                seed_yaml_path=seed_path,
                augmenter=augmenter,
                neo4j_driver=driver,
            )
            report = loader.load(
                dry_run=False,
                check_schema=args.check_schema_first,
            )
            print(
                f"Loaded: indicators {report.indicators_created} created / "
                f"{report.indicators_unchanged} unchanged; "
                f"AFFECTS {report.affects_created} created / "
                f"{report.affects_unchanged} unchanged; "
                f"DRIVES {report.drives_created} created / "
                f"{report.drives_unchanged} unchanged; "
                f"degraded edges: {report.degraded_edges}"
            )
        finally:
            driver.close()
    finally:
        augmenter.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
