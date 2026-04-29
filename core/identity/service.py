"""Identity resolution service with MongoDB fallback."""

import json
import logging
from datetime import datetime, timezone
from typing import Any

try:
    from pymongo import MongoClient
    from pymongo.database import Database
    from pymongo.errors import PyMongoError
except ImportError:
    MongoClient = None
    Database = None
    PyMongoError = Exception

# Identity resolution logic inlined from fingpt_core.identity
# (VM107 runs in Docker without fingpt_core installed)

VALID_DOMAINS = {"knowledge", "operational", "dataset", "agent"}

LEGACY_DOMAIN_MAP = {
    "concept": "knowledge",
    "method": "knowledge",
    "metric": "knowledge",
    "regime": "knowledge",
    "person": "knowledge",
    "org": "knowledge",
    "event": "knowledge",
    "time_period": "knowledge",
    "feature": "operational",
    "instrument": "operational",
    "strategy": "operational",
    "signal": "operational",
    "dataset": "dataset",
}


def _is_canonical(id_value: str) -> bool:
    """Check if ID is canonical (3-part format with valid domain)."""
    if not id_value:
        return False
    parts = id_value.split(":", maxsplit=2)
    if len(parts) < 3:
        return False
    return all(p.strip() for p in parts) and parts[0] in VALID_DOMAINS


def derive_if_possible(legacy_id: str) -> str | None:
    """Derive canonical ID from legacy ID if possible."""
    if _is_canonical(legacy_id):
        return legacy_id
    parts = legacy_id.split(":", maxsplit=1)
    if len(parts) == 2:
        legacy_type, key = parts
        if legacy_type in LEGACY_DOMAIN_MAP:
            domain = LEGACY_DOMAIN_MAP[legacy_type]
            return f"{domain}:{legacy_type}:{key}"
    return None


class IdentityService:
    """Identity resolution service - local derivation + MongoDB registry."""

    def __init__(self, mongo_db: Any):
        """Initialize identity service.

        Args:
            mongo_db: pymongo Database instance (fingpt_agents)
        """
        self.db = mongo_db
        self.logger = logging.getLogger(__name__)

    def resolve(self, id_value: str, id_type: str = "unknown") -> dict:
        """Resolve identity to canonical ID.

        Resolution strategy:
        1. Try local derivation (O(1), 80-90% hit rate)
        2. Fall back to MongoDB identity_links registry
        3. Return not_found if neither succeeds

        Args:
            id_value: ID to resolve
            id_type: Type hint for the ID (metadata only)

        Returns:
            dict with keys: canonical_id, resolved_from, resolution_method, aliases
        """
        # Log resolution attempt
        self._log(
            "info",
            "Identity resolution started",
            {
                "id_value": id_value,
                "id_type": id_type,
                "resolution_method": "attempting_local",
            },
        )

        # Step 1: Try local derivation
        canonical = derive_if_possible(id_value)
        if canonical:
            self._log(
                "info",
                "Local derivation succeeded",
                {
                    "id_value": id_value,
                    "canonical_id": canonical,
                    "resolution_method": "local",
                },
            )
            return {
                "canonical_id": canonical,
                "resolved_from": id_value,
                "resolution_method": "local",
                "aliases": [],  # Local derivation doesn't have alias info
            }

        # Step 2: MongoDB registry lookup
        if self.db is None:
            self._log(
                "warning",
                "MongoDB unavailable for registry lookup",
                {"id_value": id_value},
            )
            return {
                "canonical_id": None,
                "resolved_from": id_value,
                "resolution_method": "not_found",
                "aliases": [],
            }

        try:
            # Query identity_links collection
            link = self.db.identity_links.find_one({"system_id": id_value})

            if link:
                canonical_id = link.get("canonical_id")
                self._log(
                    "info",
                    "Registry lookup succeeded",
                    {
                        "id_value": id_value,
                        "canonical_id": canonical_id,
                        "resolution_method": "registry",
                    },
                )

                # Get aliases for this canonical ID
                aliases = self.get_aliases(canonical_id)

                return {
                    "canonical_id": canonical_id,
                    "resolved_from": id_value,
                    "resolution_method": "registry",
                    "aliases": aliases,
                }

            # Not found
            self._log(
                "info",
                "Identity not found",
                {"id_value": id_value, "resolution_method": "not_found"},
            )
            return {
                "canonical_id": None,
                "resolved_from": id_value,
                "resolution_method": "not_found",
                "aliases": [],
            }

        except Exception as e:
            self._log(
                "error",
                "MongoDB query failed",
                {"id_value": id_value, "error": str(e)},
            )
            # Graceful degradation
            return {
                "canonical_id": None,
                "resolved_from": id_value,
                "resolution_method": "not_found",
                "aliases": [],
            }

    def resolve_bulk(self, ids: list[str]) -> dict[str, dict | None]:
        """Bulk resolve identities.

        Optimized: local first, then single MongoDB $in query.

        Args:
            ids: List of IDs to resolve

        Returns:
            dict mapping id -> resolution result (or None if error)
        """
        results = {}

        # Phase 1: Local derivation for all IDs
        remaining_ids = []
        for id_value in ids:
            canonical = derive_if_possible(id_value)
            if canonical:
                results[id_value] = {
                    "canonical_id": canonical,
                    "resolved_from": id_value,
                    "resolution_method": "local",
                    "aliases": [],
                }
            else:
                remaining_ids.append(id_value)

        # Phase 2: Batch MongoDB lookup for remaining IDs
        if remaining_ids and self.db is not None:
            try:
                # Single $in query for efficiency
                links = self.db.identity_links.find(
                    {"system_id": {"$in": remaining_ids}}
                )

                # Build lookup dict
                link_map = {}
                for link in links:
                    system_id = link.get("system_id")
                    canonical_id = link.get("canonical_id")
                    link_map[system_id] = canonical_id

                # Resolve each remaining ID
                for id_value in remaining_ids:
                    if id_value in link_map:
                        canonical_id = link_map[id_value]
                        aliases = self.get_aliases(canonical_id)
                        results[id_value] = {
                            "canonical_id": canonical_id,
                            "resolved_from": id_value,
                            "resolution_method": "registry",
                            "aliases": aliases,
                        }
                    else:
                        results[id_value] = {
                            "canonical_id": None,
                            "resolved_from": id_value,
                            "resolution_method": "not_found",
                            "aliases": [],
                        }

            except Exception as e:
                self._log(
                    "error", "Bulk MongoDB query failed", {"error": str(e)}
                )
                # Mark remaining IDs as not found
                for id_value in remaining_ids:
                    if id_value not in results:
                        results[id_value] = {
                            "canonical_id": None,
                            "resolved_from": id_value,
                            "resolution_method": "not_found",
                            "aliases": [],
                        }
        else:
            # MongoDB unavailable - mark remaining as not found
            for id_value in remaining_ids:
                results[id_value] = {
                    "canonical_id": None,
                    "resolved_from": id_value,
                    "resolution_method": "not_found",
                    "aliases": [],
                }

        self._log(
            "info",
            "Bulk resolution complete",
            {
                "total_ids": len(ids),
                "local_resolved": len(ids) - len(remaining_ids),
                "registry_resolved": sum(
                    1
                    for r in results.values()
                    if r and r.get("resolution_method") == "registry"
                ),
                "not_found": sum(
                    1
                    for r in results.values()
                    if r and r.get("resolution_method") == "not_found"
                ),
            },
        )

        return results

    def register_link(
        self,
        canonical_id: str,
        system: str,
        system_id: str,
        link_type: str = None,
        metadata: dict = None,
    ) -> bool:
        """Register identity link in MongoDB.

        Args:
            canonical_id: Canonical ID
            system: System name (qdrant, neo4j, parquet, mongo)
            system_id: System-specific ID
            link_type: Optional link type
            metadata: Optional metadata dict

        Returns:
            True if created/updated, False on error
        """
        if self.db is None:
            self._log(
                "warning", "MongoDB unavailable for link registration", {}
            )
            return False

        try:
            doc = {
                "_id": canonical_id,
                "canonical_id": canonical_id,
                "system": system,
                "system_id": system_id,
                "created_at": datetime.now(timezone.utc),
                "schema_version": 1,
            }

            if link_type:
                doc["link_type"] = link_type
            if metadata:
                doc["metadata"] = metadata

            # Upsert based on (system, system_id) unique index
            result = self.db.identity_links.update_one(
                {"system": system, "system_id": system_id},
                {"$set": doc, "$setOnInsert": {"created_at": doc["created_at"]}},
                upsert=True,
            )

            self._log(
                "info",
                "Identity link registered",
                {
                    "canonical_id": canonical_id,
                    "system": system,
                    "system_id": system_id,
                    "upserted": result.upserted_id is not None,
                },
            )

            return True

        except Exception as e:
            self._log(
                "error",
                "Link registration failed",
                {
                    "canonical_id": canonical_id,
                    "system": system,
                    "system_id": system_id,
                    "error": str(e),
                },
            )
            return False

    def get_aliases(self, canonical_id: str) -> list[dict]:
        """Get all aliases for a canonical ID.

        Args:
            canonical_id: Canonical ID

        Returns:
            List of alias dicts with keys: system, system_id, link_type, metadata
        """
        if self.db is None:
            return []

        try:
            links = self.db.identity_links.find({"canonical_id": canonical_id})

            aliases = []
            for link in links:
                alias = {
                    "system": link.get("system"),
                    "system_id": link.get("system_id"),
                }
                if "link_type" in link:
                    alias["link_type"] = link["link_type"]
                if "metadata" in link:
                    alias["metadata"] = link["metadata"]
                aliases.append(alias)

            return aliases

        except Exception as e:
            self._log(
                "error",
                "Failed to get aliases",
                {"canonical_id": canonical_id, "error": str(e)},
            )
            return []

    def _log(self, level: str, message: str, extra: dict):
        """Structured JSON logging with ISO 8601 Z suffix.

        Args:
            level: Log level (info, warning, error)
            message: Log message
            extra: Additional fields to include
        """
        log_entry = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "level": level.upper(),
            "message": message,
            **extra,
        }

        log_func = getattr(self.logger, level, self.logger.info)
        log_func(json.dumps(log_entry))
