"""
Budget usage migration from agent_zero to fingpt_agents.

Copies all budget_usage documents from Phase 38's agent_zero database
to the new fingpt_agents database, preserving historical data.
"""
from datetime import datetime, timezone


def upgrade(context: dict) -> None:
    """
    Migrate budget_usage data from agent_zero to fingpt_agents.

    Args:
        context: Migration context with mongo dict of databases
    """
    mongo_dbs = context.get("mongo", {})

    # Verify both databases are available
    if "agent_zero" not in mongo_dbs:
        print("SKIP: agent_zero database not found (no data to migrate)")
        return

    source_db = mongo_dbs["agent_zero"]
    target_db = mongo_dbs["fingpt_agents"]

    source_collection = source_db["budget_usage"]
    target_collection = target_db["budget_usage"]

    # Read all documents from source
    source_docs = list(source_collection.find())

    if not source_docs:
        print("SKIP: No budget_usage documents to migrate")
        return

    # Migrate documents with schema_version
    migrated_count = 0
    total_spend = 0.0
    date_range = {"min": None, "max": None}

    for doc in source_docs:
        # Add schema_version to migrated document
        doc["schema_version"] = 1

        # Track migration timestamp
        doc["migrated_at"] = datetime.now(timezone.utc)

        # Upsert to target (idempotent)
        target_collection.replace_one(
            {"_id": doc["_id"]},
            doc,
            upsert=True
        )

        migrated_count += 1

        # Track statistics
        if "total_spend" in doc:
            total_spend += doc["total_spend"]

        # Track date range
        doc_date = doc["_id"]  # _id is date string
        if date_range["min"] is None or doc_date < date_range["min"]:
            date_range["min"] = doc_date
        if date_range["max"] is None or doc_date > date_range["max"]:
            date_range["max"] = doc_date

    # Verify document count matches
    target_count = target_collection.count_documents({})
    assert target_count == migrated_count, (
        f"Migration count mismatch: migrated {migrated_count}, target has {target_count}"
    )

    print(f"Migrated {migrated_count} budget_usage documents")
    print(f"  Total spend: ${total_spend:.2f}")
    print(f"  Date range: {date_range['min']} to {date_range['max']}")
    print(f"  Source: agent_zero.budget_usage (preserved)")
    print(f"  Target: fingpt_agents.budget_usage")


def downgrade(context: dict) -> None:
    """
    Drop budget_usage from fingpt_agents (data preserved in agent_zero).

    Args:
        context: Migration context with mongo dict of databases
    """
    target_db = context["mongo"]["fingpt_agents"]
    target_db.drop_collection("budget_usage")

    print("Dropped budget_usage from fingpt_agents")
    print("  Source data preserved in agent_zero.budget_usage")
