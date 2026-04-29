"""
Migration runner for cross-system database migrations.

Executes numbered migration scripts with checksum tracking,
environment awareness, and idempotent execution.
"""
import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any

from .registry import discover_migrations


class MigrationError(Exception):
    """Raised when migration fails or checksum mismatch detected."""
    pass


class MigrationRunner:
    """
    Cross-system migration runner.

    Supports MongoDB, Neo4j, and Qdrant migrations with:
    - Numbered script execution (001_*, 002_*, etc.)
    - SHA256 checksum tracking to detect drift
    - Environment-aware execution (dev/prod)
    - Idempotent re-runs
    - Dry-run mode
    """

    def __init__(self, context: dict[str, Any]):
        """
        Initialize migration runner.

        Args:
            context: Dictionary with keys:
                - mongo: dict of db_name -> pymongo.Database
                - neo4j: Neo4j session or None
                - qdrant: Qdrant client or None
        """
        self.context = context

        # Get fingpt_agents database for migration tracking
        mongo_dbs = context.get("mongo", {})
        if "fingpt_agents" not in mongo_dbs:
            raise MigrationError("fingpt_agents database required in context['mongo']")

        self._db = mongo_dbs["fingpt_agents"]
        self._migrations_collection = self._db["migrations_applied"]

        # Environment detection
        self._environment = (
            os.environ.get("DAGSTER_DEPLOYMENT") or
            os.environ.get("FINGPT_ENV") or
            "dev"
        )

    def run_pending(self, dry_run: bool = False) -> list[str]:
        """
        Discover and execute all pending migrations.

        Args:
            dry_run: If True, log what would happen without executing

        Returns:
            List of migration IDs that were executed (or would be)

        Raises:
            MigrationError: If migration fails or checksum mismatch
        """
        all_migrations = discover_migrations()
        applied_migrations = self._get_applied_migrations()

        executed = []

        for migration in all_migrations:
            migration_id = migration.id

            # Check if already applied
            if migration_id in applied_migrations:
                # Verify checksum hasn't changed
                stored_checksum = applied_migrations[migration_id]["checksum"]
                if migration.checksum != stored_checksum:
                    raise MigrationError(
                        f"Checksum mismatch for {migration_id}. "
                        f"Expected {stored_checksum}, got {migration.checksum}. "
                        "Migration file has been modified after execution."
                    )

                self._log(f"SKIP {migration_id} (already applied)", dry_run)
                continue

            # Execute migration
            self._log(f"RUN {migration_id}", dry_run)

            if not dry_run:
                try:
                    # Execute upgrade function
                    migration.module.upgrade(self.context)

                    # Record in migrations_applied
                    self._record_migration(migration)

                    self._log(f"OK {migration_id}", dry_run)

                except Exception as e:
                    self._log(f"FAIL {migration_id}: {e}", dry_run)
                    raise MigrationError(f"Migration {migration_id} failed: {e}") from e

            executed.append(migration_id)

        return executed

    def rollback(self, migration_id: str, dry_run: bool = False) -> None:
        """
        Rollback a specific migration.

        Args:
            migration_id: Migration ID (e.g., "001_init_fingpt_agents")
            dry_run: If True, log what would happen without executing

        Raises:
            MigrationError: If migration not found or rollback fails
        """
        all_migrations = discover_migrations()
        migration = next((m for m in all_migrations if m.id == migration_id), None)

        if not migration:
            raise MigrationError(f"Migration {migration_id} not found")

        applied_migrations = self._get_applied_migrations()
        if migration_id not in applied_migrations:
            self._log(f"SKIP rollback {migration_id} (not applied)", dry_run)
            return

        self._log(f"ROLLBACK {migration_id}", dry_run)

        if not dry_run:
            try:
                # Execute downgrade function
                migration.module.downgrade(self.context)

                # Remove from migrations_applied
                self._migrations_collection.delete_one({"_id": migration_id})

                self._log(f"OK rollback {migration_id}", dry_run)

            except Exception as e:
                self._log(f"FAIL rollback {migration_id}: {e}", dry_run)
                raise MigrationError(f"Rollback {migration_id} failed: {e}") from e

    def _get_applied_migrations(self) -> dict[str, dict]:
        """Get all applied migrations from database."""
        applied = {}
        for doc in self._migrations_collection.find():
            applied[doc["_id"]] = {
                "checksum": doc["checksum"],
                "applied_at": doc["applied_at"],
                "environment": doc.get("environment", "unknown"),
                "version": doc.get("version", 1)
            }
        return applied

    def _record_migration(self, migration) -> None:
        """Record migration execution in database."""
        self._migrations_collection.insert_one({
            "_id": migration.id,
            "checksum": migration.checksum,
            "applied_at": datetime.now(timezone.utc),
            "environment": self._environment,
            "version": 1
        })

    def _log(self, message: str, dry_run: bool) -> None:
        """Structured JSON logging."""
        log_entry = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "component": "MigrationRunner",
            "environment": self._environment,
            "dry_run": dry_run,
            "message": message
        }
        print(json.dumps(log_entry))
