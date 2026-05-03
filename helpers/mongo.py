"""Shared MongoDB client helper.

Provides get_mongo_db() — resolves MONGODB_URI from environment and returns
a pymongo Database handle. Used by Phase 44 endpoint + future callers.

Pattern: same env-fallback convention as router extensions (_router_decide.py).
"""
from __future__ import annotations

import os
from typing import Any


def get_mongo_db() -> Any:
    """Return a pymongo Database handle for the FinGPT agents database.

    Database name is extracted from the URI path, defaulting to 'fingpt_agents'
    if the URI does not include a path component.

    Returns:
        pymongo.Database

    Raises:
        RuntimeError: MONGODB_URI env var is not set.
        ImportError: pymongo is not installed.
    """
    import pymongo  # type: ignore[import]

    mongo_uri = os.environ.get("MONGODB_URI")
    if not mongo_uri:
        raise RuntimeError(
            "MONGODB_URI environment variable is required but not set. "
            "Set MONGODB_URI=mongodb://<host>:<port>/<dbname> in your environment."
        )

    # Extract database name from URI path component.
    # URI format: mongodb://host:port/dbname  or  mongodb://host:port  (no db name)
    if "/" in mongo_uri and not mongo_uri.rstrip("/").endswith(":27017"):
        db_name = mongo_uri.rstrip("/").split("/")[-1] or "fingpt_agents"
        # Strip query string from db name if present
        db_name = db_name.split("?")[0] or "fingpt_agents"
    else:
        db_name = "fingpt_agents"

    client = pymongo.MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    return client[db_name]
