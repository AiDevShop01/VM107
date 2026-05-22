"""
Migration script discovery and registration.

Scans scripts/ directory for numbered migration files
and provides ordered list with checksum validation.
"""
import hashlib
import importlib.util
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class MigrationScript:
    """Represents a discovered migration script.

    Two conventions are supported:
      - "context" style: module exposes ``upgrade(context: dict) -> None`` and
        ``downgrade(context: dict) -> None``. The context dict contains
        ``mongo`` (dict of db name -> pymongo.Database), ``neo4j`` (driver),
        ``qdrant`` (client). Older migrations (001-006, 004, 010).
      - "db" style: module exposes ``up(db: pymongo.Database) -> None`` and
        ``down(db: pymongo.Database) -> None``. The runner passes the
        ``fingpt_agents`` database directly. Newer migrations (007+, the
        Phase 47.6 stamping set, Phase 48 refinement collections).
    """
    id: str          # e.g., "001_init_fingpt_agents"
    number: int      # e.g., 1
    name: str        # e.g., "init_fingpt_agents"
    module: Any      # Imported module with upgrade/downgrade or up/down
    checksum: str    # SHA256 hash of file contents
    style: str = "context"  # "context" (upgrade/downgrade(ctx)) or "db" (up/down(db))


def discover_migrations() -> list[MigrationScript]:
    """
    Discover migration scripts from scripts/ directory.

    Returns:
        List of MigrationScript objects ordered by number

    Raises:
        ValueError: If migration files are malformed
    """
    scripts_dir = Path(__file__).parent / "scripts"

    if not scripts_dir.exists():
        return []

    pattern = re.compile(r"^(\d{3})_(.+)\.py$")
    migrations = []

    for filepath in scripts_dir.glob("*.py"):
        if filepath.name.startswith("__"):
            continue

        match = pattern.match(filepath.name)
        if not match:
            continue

        number_str, name = match.groups()
        number = int(number_str)
        migration_id = f"{number_str}_{name}"

        # Compute checksum
        checksum = _compute_checksum(filepath)

        # Import module
        module = _import_migration(filepath)

        # Detect convention: prefer "context" (upgrade/downgrade) when present,
        # fall back to "db" (up/down). Reject if neither is exposed.
        if hasattr(module, "upgrade") and hasattr(module, "downgrade"):
            style = "context"
        elif hasattr(module, "up") and hasattr(module, "down"):
            style = "db"
        else:
            raise ValueError(
                f"Migration {migration_id} must expose either "
                f"upgrade(context)+downgrade(context) or up(db)+down(db)"
            )

        migrations.append(
            MigrationScript(
                id=migration_id,
                number=number,
                name=name,
                module=module,
                checksum=checksum,
                style=style,
            )
        )

    # Sort by number
    migrations.sort(key=lambda m: m.number)

    return migrations


def _compute_checksum(filepath: Path) -> str:
    """Compute SHA256 checksum of file."""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        sha256.update(f.read())
    return sha256.hexdigest()


def _import_migration(filepath: Path) -> Any:
    """Dynamically import migration module."""
    spec = importlib.util.spec_from_file_location(filepath.stem, filepath)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load migration from {filepath}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module
