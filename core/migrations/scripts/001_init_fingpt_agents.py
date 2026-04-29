"""
Initial fingpt_agents database setup.

Creates 12 collections:
- 5 active collections with full JSON schema validators
- 6 stub collections with minimal schema
- 1 graph_events collection for Neo4j audit trail
"""
from datetime import datetime, timezone


def upgrade(context: dict) -> None:
    """
    Create fingpt_agents database collections with validators.

    Args:
        context: Migration context with mongo dict of databases
    """
    db = context["mongo"]["fingpt_agents"]

    # ===== ACTIVE COLLECTIONS (5) =====

    # 1. agent_tasks - Task execution tracking
    db.create_collection(
        "agent_tasks",
        validator={
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["_id", "agent_name", "task_type", "status", "created_at", "schema_version"],
                "properties": {
                    "_id": {"bsonType": "string"},
                    "agent_name": {"bsonType": "string"},
                    "task_type": {"bsonType": "string"},
                    "status": {
                        "enum": ["pending", "running", "complete", "failed", "cancelled"]
                    },
                    "created_at": {"bsonType": "date"},
                    "schema_version": {"bsonType": "int"},
                    "execution_trace": {"bsonType": "array"},
                    "token_count": {"bsonType": "int"},
                    "cost_usd": {"bsonType": "double"},
                    "input_context": {"bsonType": "object"},
                    "output_result": {"bsonType": "object"},
                    "error": {"bsonType": "object"},
                    "updated_at": {"bsonType": "date"},
                    "completed_at": {"bsonType": "date"}
                }
            }
        }
    )
    db["agent_tasks"].create_index([("agent_name", 1), ("status", 1)])
    db["agent_tasks"].create_index([("created_at", -1)])
    db["agent_tasks"].create_index([("status", 1), ("created_at", -1)])

    # 2. agent_memory - Long-term agent memory
    db.create_collection(
        "agent_memory",
        validator={
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["_id", "agent_name", "summary", "area", "confidence", "created_at", "schema_version"],
                "properties": {
                    "_id": {"bsonType": "string"},
                    "agent_name": {"bsonType": "string"},
                    "summary": {"bsonType": "string"},
                    "area": {"bsonType": "string"},
                    "confidence": {
                        "bsonType": "double",
                        "minimum": 0.0,
                        "maximum": 1.0
                    },
                    "created_at": {"bsonType": "date"},
                    "schema_version": {"bsonType": "int"},
                    "embedding_id": {"bsonType": "string"},
                    "tags": {"bsonType": "array"},
                    "source_task_id": {"bsonType": "string"},
                    "updated_at": {"bsonType": "date"},
                    "expires_at": {"bsonType": "date"}
                }
            }
        }
    )
    db["agent_memory"].create_index([("embedding_id", 1)])
    db["agent_memory"].create_index([("confidence", -1), ("created_at", -1)])
    db["agent_memory"].create_index([("agent_name", 1), ("area", 1)])
    # TTL index for automatic expiration (90 days)
    db["agent_memory"].create_index([("expires_at", 1)], expireAfterSeconds=7776000)

    # 3. agent_decisions - Decision tracking with cross-system links
    db.create_collection(
        "agent_decisions",
        validator={
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["_id", "agent_name", "decision_type", "rationale", "confidence", "created_at", "schema_version"],
                "properties": {
                    "_id": {"bsonType": "string"},
                    "agent_name": {"bsonType": "string"},
                    "decision_type": {"bsonType": "string"},
                    "rationale": {"bsonType": "string"},
                    "confidence": {
                        "bsonType": "double",
                        "minimum": 0.0,
                        "maximum": 1.0
                    },
                    "created_at": {"bsonType": "date"},
                    "schema_version": {"bsonType": "int"},
                    "inputs": {"bsonType": "object"},
                    "neo4j_refs": {
                        "bsonType": "array",
                        "items": {"bsonType": "string"}
                    },
                    "qdrant_refs": {
                        "bsonType": "array",
                        "items": {"bsonType": "string"}
                    },
                    "parquet_refs": {
                        "bsonType": "array",
                        "items": {"bsonType": "string"}
                    },
                    "updated_at": {"bsonType": "date"}
                }
            }
        }
    )
    db["agent_decisions"].create_index([("agent_name", 1), ("decision_type", 1)])
    db["agent_decisions"].create_index([("created_at", -1)])

    # 4. agent_context_snapshots - Point-in-time context captures
    db.create_collection(
        "agent_context_snapshots",
        validator={
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["_id", "task_id", "snapshot_type", "created_at", "schema_version"],
                "properties": {
                    "_id": {"bsonType": "string"},
                    "task_id": {"bsonType": "string"},
                    "snapshot_type": {"bsonType": "string"},
                    "created_at": {"bsonType": "date"},
                    "schema_version": {"bsonType": "int"},
                    "market_state_refs": {"bsonType": "object"},
                    "features_used": {"bsonType": "array"},
                    "graph_context": {"bsonType": "object"},
                    "vector_context": {"bsonType": "object"},
                    "parquet_refs": {"bsonType": "array"},
                    "expires_at": {"bsonType": "date"}
                }
            }
        }
    )
    db["agent_context_snapshots"].create_index([("task_id", 1)])
    db["agent_context_snapshots"].create_index([("created_at", -1)])
    # TTL index for automatic expiration (30 days)
    db["agent_context_snapshots"].create_index([("expires_at", 1)], expireAfterSeconds=2592000)

    # 5. identity_links - Cross-system canonical ID mapping
    db.create_collection(
        "identity_links",
        validator={
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["_id", "canonical_id", "system", "system_id", "created_at", "schema_version"],
                "properties": {
                    "_id": {"bsonType": "string"},
                    "canonical_id": {"bsonType": "string"},
                    "system": {"bsonType": "string"},
                    "system_id": {"bsonType": "string"},
                    "created_at": {"bsonType": "date"},
                    "schema_version": {"bsonType": "int"},
                    "link_type": {"bsonType": "string"},
                    "metadata": {"bsonType": "object"},
                    "updated_at": {"bsonType": "date"}
                }
            }
        }
    )
    db["identity_links"].create_index([("canonical_id", 1)])
    db["identity_links"].create_index([("system", 1), ("system_id", 1)], unique=True)
    db["identity_links"].create_index([("canonical_id", 1), ("system", 1)], unique=True)

    # ===== STUB COLLECTIONS (6) =====

    stub_validator = {
        "$jsonSchema": {
            "bsonType": "object",
            "required": ["_id", "created_at", "schema_version"],
            "properties": {
                "_id": {"bsonType": "string"},
                "created_at": {"bsonType": "date"},
                "schema_version": {"bsonType": "int"}
            },
            "additionalProperties": True
        }
    }

    stub_collections = [
        "agent_objectives",
        "agent_progress",
        "brain_state",
        "agent_runs",
        "strategies",
        "backtest_results"
    ]

    for collection_name in stub_collections:
        db.create_collection(collection_name, validator=stub_validator)

    # ===== GRAPH EVENTS COLLECTION (1) =====

    # graph_events - Neo4j mutation audit trail
    db.create_collection(
        "graph_events",
        validator={
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["_id", "event_type", "created_at", "schema_version"],
                "properties": {
                    "_id": {"bsonType": "string"},
                    "event_type": {"bsonType": "string"},
                    "source_id": {"bsonType": "string"},
                    "target_id": {"bsonType": "string"},
                    "relationship_type": {"bsonType": "string"},
                    "old_status": {"bsonType": "string"},
                    "new_status": {"bsonType": "string"},
                    "confidence_change": {"bsonType": "double"},
                    "created_at": {"bsonType": "date"},
                    "schema_version": {"bsonType": "int"}
                }
            }
        }
    )
    db["graph_events"].create_index([("event_type", 1), ("created_at", -1)])
    db["graph_events"].create_index([("created_at", -1)])

    print(f"Created 12 collections in fingpt_agents database:")
    print(f"  - 5 active: agent_tasks, agent_memory, agent_decisions, agent_context_snapshots, identity_links")
    print(f"  - 6 stubs: {', '.join(stub_collections)}")
    print(f"  - 1 audit: graph_events")


def downgrade(context: dict) -> None:
    """
    Drop all collections created by this migration.

    Args:
        context: Migration context with mongo dict of databases
    """
    db = context["mongo"]["fingpt_agents"]

    collections = [
        "agent_tasks",
        "agent_memory",
        "agent_decisions",
        "agent_context_snapshots",
        "identity_links",
        "agent_objectives",
        "agent_progress",
        "brain_state",
        "agent_runs",
        "strategies",
        "backtest_results",
        "graph_events"
    ]

    for collection_name in collections:
        db.drop_collection(collection_name)

    print(f"Dropped {len(collections)} collections from fingpt_agents database")
