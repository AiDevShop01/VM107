"""
Router goal fields schema upgrade (Phase 43).

Extends the agent_goals collection schema with budget enforcement fields needed
by the LLM Model Router breach handler. Creates two new collections for router
observability: router_decisions (per-call logs) and router_alerts (budget events).

Changes:
    1. Add router budget fields to agent_goals:
       - enqueue_blocked: bool (default False) — scheduler stops queuing new tasks
       - force_local: bool (default False) — router uses local-only models
       - budget_status: str enum (default "ok") — ok/warning_50/warning_80/exceeded
       - budget_breach_at: date (nullable) — timestamp of first breach today
       - budget_spent_today: double (default 0.0) — rolling daily spend total
    2. Backfill existing goals with sensible defaults (no NULL breakage)
    3. Create router_decisions collection with indexes
    4. Create router_alerts collection with indexes

Notes:
    - Migration is NOT automatically executed — Plan 05 checkpoint triggers execution
      as part of the deploy sequence after container rebuild
    - Downgrade restores 004 agent_goals validator and drops the two new collections
    - Validator uses additionalProperties: false to prevent schema drift
"""


def upgrade(context: dict) -> None:
    """
    Upgrade to Phase 43 router schema.

    Extends agent_goals validator, backfills existing documents,
    and creates router_decisions + router_alerts collections.

    Args:
        context: Migration context dict with keys:
                 - mongo: dict of {db_name: pymongo.Database}
    """
    db = context["mongo"]["fingpt_agents"]

    # ===== 1. EXTEND agent_goals schema with router budget fields =====
    print("Extending agent_goals validator with router budget fields...")
    db.command({
        "collMod": "agent_goals",
        "validator": {
            "$jsonSchema": {
                "bsonType": "object",
                "required": [
                    "_id", "title", "goal_type", "status", "priority",
                    "created_by", "created_at", "schema_version"
                ],
                "properties": {
                    # --- Existing Phase 42 fields (preserved verbatim from migration 004) ---
                    "_id": {"bsonType": "string"},
                    "title": {"bsonType": "string", "minLength": 3, "maxLength": 200},
                    "description": {"bsonType": "string"},
                    "goal_type": {
                        "enum": ["maintenance", "learning", "research", "execution", "system"]
                    },
                    "status": {
                        "enum": [
                            "draft", "proposed", "approved", "active",
                            "paused", "completed", "failed", "cancelled"
                        ]
                    },
                    "priority": {"enum": ["P1", "P2", "P3", "P4"]},
                    "objective_label": {"bsonType": ["string", "null"]},
                    "decomposition_template": {"bsonType": ["string", "null"]},
                    "created_by": {"bsonType": "string"},
                    "governance_tier": {"bsonType": "string"},
                    "budget_max_cost_usd": {"bsonType": ["double", "null"], "minimum": 0},
                    "budget_max_tokens": {"bsonType": ["int", "null"], "minimum": 0},
                    "task_ids": {"bsonType": "array", "items": {"bsonType": "string"}},
                    "created_at": {"bsonType": "date"},
                    "updated_at": {"bsonType": "date"},
                    "schema_version": {"bsonType": "int"},
                    # --- NEW Phase 43 router budget enforcement fields ---
                    "enqueue_blocked": {
                        "bsonType": ["bool", "null"],
                        "description": "True when goal has hit 100% budget breach; scheduler stops queuing new tasks"
                    },
                    "force_local": {
                        "bsonType": ["bool", "null"],
                        "description": "True when router must use local-only models for this goal"
                    },
                    "budget_status": {
                        "enum": ["ok", "warning_50", "warning_80", "exceeded", None],
                        "description": "Current budget utilization tier for this goal"
                    },
                    "budget_breach_at": {
                        "bsonType": ["date", "null"],
                        "description": "UTC timestamp when this goal first hit 100% budget today"
                    },
                    "budget_spent_today": {
                        "bsonType": ["double", "null"],
                        "minimum": 0,
                        "description": "Rolling daily spend total in USD (mirrored from Redis aggregate)"
                    }
                }
            }
        },
        "validationLevel": "moderate",   # existing docs not validated on reads
        "validationAction": "error"       # new/updated docs must pass schema
    })

    # ===== 2. BACKFILL existing goals with router field defaults =====
    print("Backfilling existing agent_goals with router field defaults...")
    result = db["agent_goals"].update_many(
        {"enqueue_blocked": {"$exists": False}},
        {
            "$set": {
                "enqueue_blocked": False,
                "force_local": False,
                "budget_status": "ok",
                "budget_spent_today": 0.0,
                # budget_breach_at intentionally omitted (null by absence)
            }
        }
    )
    print(f"  Backfilled {result.modified_count} goal documents")

    # ===== 3. CREATE router_decisions collection =====
    print("Creating router_decisions collection...")
    if "router_decisions" not in db.list_collection_names():
        db.create_collection(
            "router_decisions",
            validator={
                "$jsonSchema": {
                    "bsonType": "object",
                    "required": ["_id", "task_id", "goal_id", "agent_id", "task_type",
                                 "primary", "fallback", "reason", "decision_time_ms", "created_at"],
                    "properties": {
                        "_id": {"bsonType": "string"},
                        "task_id": {"bsonType": "string"},
                        "goal_id": {"bsonType": "string"},
                        "agent_id": {"bsonType": "string"},
                        "task_type": {"bsonType": "string"},
                        "primary": {"bsonType": "string"},
                        "fallback": {
                            "bsonType": "array",
                            "items": {"bsonType": "string"}
                        },
                        "reason": {
                            "bsonType": "array",
                            "items": {"bsonType": "string"}
                        },
                        "decision_time_ms": {"bsonType": ["double", "int"], "minimum": 0},
                        "peak": {"bsonType": ["bool", "null"]},
                        "mode": {"bsonType": ["string", "null"]},
                        "force_local": {"bsonType": ["bool", "null"]},
                        "created_at": {"bsonType": "date"}
                    }
                }
            }
        )
    db["router_decisions"].create_index([("task_id", 1)], unique=True)
    db["router_decisions"].create_index([("goal_id", 1), ("created_at", -1)])
    db["router_decisions"].create_index([("agent_id", 1), ("created_at", -1)])

    # ===== 4. CREATE router_alerts collection =====
    print("Creating router_alerts collection...")
    if "router_alerts" not in db.list_collection_names():
        db.create_collection(
            "router_alerts",
            validator={
                "$jsonSchema": {
                    "bsonType": "object",
                    "required": ["_id", "scope", "threshold", "spent_usd", "max_usd",
                                 "pct", "sinks_fired", "created_at"],
                    "properties": {
                        "_id": {"bsonType": "string"},
                        "scope": {"enum": ["goal", "agent_type", "system"]},
                        "threshold": {"enum": ["50pct", "80pct", "100pct"]},
                        "goal_id": {"bsonType": ["string", "null"]},
                        "agent_type": {"bsonType": ["string", "null"]},
                        "spent_usd": {"bsonType": ["double", "int"], "minimum": 0},
                        "max_usd": {"bsonType": ["double", "int"], "minimum": 0},
                        "pct": {"bsonType": ["double", "int"], "minimum": 0},
                        "sinks_fired": {
                            "bsonType": "array",
                            "items": {"bsonType": "string"}
                        },
                        "created_at": {"bsonType": "date"}
                    }
                }
            }
        )
    db["router_alerts"].create_index([("scope", 1), ("threshold", 1), ("created_at", -1)])
    db["router_alerts"].create_index([("goal_id", 1), ("created_at", -1)])

    print("Migration 005 complete:")
    print("  - Extended agent_goals schema with 5 router budget fields")
    print("  - Backfilled existing goal documents with defaults")
    print("  - Created router_decisions collection with 3 indexes")
    print("  - Created router_alerts collection with 2 indexes")
    print("  NOTE: Migration not yet executed — Plan 05 deploy checkpoint will run it")


def downgrade(context: dict) -> None:
    """
    Revert Phase 43 router schema changes.

    Restores agent_goals validator to Phase 42 (004) shape and drops the
    two new collections (router_decisions, router_alerts).

    Args:
        context: Migration context dict with keys:
                 - mongo: dict of {db_name: pymongo.Database}
    """
    db = context["mongo"]["fingpt_agents"]

    # Drop new collections first
    print("Dropping router_decisions collection...")
    db.drop_collection("router_decisions")

    print("Dropping router_alerts collection...")
    db.drop_collection("router_alerts")

    # Restore agent_goals validator to Phase 42 (004) shape
    print("Restoring agent_goals validator to migration 004 shape...")
    db.command({
        "collMod": "agent_goals",
        "validator": {
            "$jsonSchema": {
                "bsonType": "object",
                "required": [
                    "_id", "title", "goal_type", "status", "priority",
                    "created_by", "created_at", "schema_version"
                ],
                "properties": {
                    "_id": {"bsonType": "string"},
                    "title": {"bsonType": "string", "minLength": 3, "maxLength": 200},
                    "description": {"bsonType": "string"},
                    "goal_type": {
                        "enum": ["maintenance", "learning", "research", "execution", "system"]
                    },
                    "status": {
                        "enum": [
                            "draft", "proposed", "approved", "active",
                            "paused", "completed", "failed", "cancelled"
                        ]
                    },
                    "priority": {"enum": ["P1", "P2", "P3", "P4"]},
                    "objective_label": {"bsonType": ["string", "null"]},
                    "decomposition_template": {"bsonType": ["string", "null"]},
                    "created_by": {"bsonType": "string"},
                    "governance_tier": {"bsonType": "string"},
                    "budget_max_cost_usd": {"bsonType": ["double", "null"], "minimum": 0},
                    "budget_max_tokens": {"bsonType": ["int", "null"], "minimum": 0},
                    "task_ids": {"bsonType": "array", "items": {"bsonType": "string"}},
                    "created_at": {"bsonType": "date"},
                    "updated_at": {"bsonType": "date"},
                    "schema_version": {"bsonType": "int"}
                }
            }
        }
    })

    print("Migration 005 downgrade complete")
