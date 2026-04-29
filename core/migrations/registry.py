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
    """Represents a discovered migration script."""
    id: str          # e.g., "001_init_fingpt_agents"
    number: int      # e.g., 1
    name: str        # e.g., "init_fingpt_agents"
    module: Any      # Imported module with upgrade/downgrade
    checksum: str    # SHA256 hash of file contents


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

        # Validate module has upgrade/downgrade
        if not hasattr(module, "upgrade"):
            raise ValueError(
                f"Migration {migration_id} missing upgrade() function"
            )
        if not hasattr(module, "downgrade"):
            raise ValueError(
                f"Migration {migration_id} missing downgrade() function"
            )

        migrations.append(
            MigrationScript(
                id=migration_id,
                number=number,
                name=name,
                module=module,
                checksum=checksum
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
