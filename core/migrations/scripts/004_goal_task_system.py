"""
Goal/Task system schema upgrade.

Renames agent_objectives → agent_goals and expands all stub collection schemas
with proper validators and indexes for the Goal/Task scheduling system.
"""


def upgrade(context: dict) -> None:
    """
    Upgrade Phase 41 stubs to Phase 42 full schemas.

    Changes:
    1. Rename agent_objectives → agent_goals
    2. Update agent_goals validator with full GoalModel schema
    3. Update agent_tasks validator with full TaskModel schema
    4. Expand brain_state validator for Brain Layer
    5. Expand agent_progress validator for progress tracking
    6. Expand agent_runs validator for run tracking

    Args:
        context: Migration context with mongo dict of databases
    """
    db = context["mongo"]["fingpt_agents"]

    # ===== 1. RENAME agent_objectives → agent_goals =====
    print("Renaming agent_objectives → agent_goals...")
    db["agent_objectives"].rename("agent_goals")

    # ===== 2. UPDATE agent_goals schema =====
    print("Updating agent_goals validator...")
    db.command({
        "collMod": "agent_goals",
        "validator": {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["_id", "title", "goal_type", "status", "priority", "created_by", "created_at", "schema_version"],
                "properties": {
                    "_id": {"bsonType": "string"},
                    "title": {"bsonType": "string", "minLength": 3, "maxLength": 200},
                    "description": {"bsonType": "string"},
                    "goal_type": {
                        "enum": ["maintenance", "learning", "research", "execution", "system"]
                    },
                    "status": {
                        "enum": ["draft", "proposed", "approved", "active", "paused", "completed", "failed", "cancelled"]
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

    # Create indexes for agent_goals
    db["agent_goals"].create_index([("status", 1), ("priority", 1), ("created_at", -1)])
    db["agent_goals"].create_index([("goal_type", 1), ("status", 1)])
    db["agent_goals"].create_index([("objective_label", 1), ("status", 1)])
    db["agent_goals"].create_index([("created_at", -1)])

    # ===== 3. UPDATE agent_tasks schema =====
    print("Updating agent_tasks validator...")
    db.command({
        "collMod": "agent_tasks",
        "validator": {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["_id", "goal_id", "task_type", "status", "priority", "created_at", "schema_version"],
                "properties": {
                    "_id": {"bsonType": "string"},
                    "goal_id": {"bsonType": "string"},
                    "task_type": {"bsonType": "string"},
                    "status": {
                        "enum": ["pending", "blocked", "queued", "running", "completed", "failed", "cancelled"]
                    },
                    "priority": {"enum": ["P1", "P2", "P3", "P4"]},
                    "dependencies": {"bsonType": "array", "items": {"bsonType": "string"}},
                    "blocked_by": {"bsonType": "array", "items": {"bsonType": "string"}},
                    "preemptible": {"bsonType": "bool"},
                    "checkpoint_interval_seconds": {"bsonType": ["int", "null"], "minimum": 1},
                    "retry_count": {"bsonType": "int", "minimum": 0},
                    "max_retries": {"bsonType": "int", "minimum": 0},
                    "estimated_cost_usd": {"bsonType": ["double", "null"], "minimum": 0},
                    "deadline": {"bsonType": ["double", "null"]},
                    "agent_name": {"bsonType": ["string", "null"]},
                    "queued_at": {"bsonType": ["date", "null"]},
                    "started_at": {"bsonType": ["date", "null"]},
                    "completed_at": {"bsonType": ["date", "null"]},
                    "created_at": {"bsonType": "date"},
                    "updated_at": {"bsonType": "date"},
                    "schema_version": {"bsonType": "int"}
                }
            }
        }
    })

    # Create indexes for agent_tasks
    db["agent_tasks"].create_index([("goal_id", 1), ("status", 1)])
    db["agent_tasks"].create_index([("status", 1), ("priority", 1)])
    db["agent_tasks"].create_index([("status", 1), ("queued_at", 1)])

    # ===== 4. UPDATE brain_state schema =====
    print("Updating brain_state validator...")
    db.command({
        "collMod": "brain_state",
        "validator": {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["_id", "updated_at", "schema_version"],
                "properties": {
                    "_id": {"bsonType": "string"},  # e.g., "brain:global" or "brain:goal:{id}"
                    "mode": {"enum": ["exploration", "exploitation", "stabilization", None]},
                    "resource_policy": {"enum": ["normal", "constrained", None]},
                    "scheduler_control": {"bsonType": ["object", "null"]},
                    "confidence_global": {"bsonType": ["double", "null"], "minimum": 0, "maximum": 1},
                    "mode_control": {"bsonType": ["object", "null"]},
                    "system_state": {"bsonType": ["object", "null"]},
                    "updated_at": {"bsonType": "date"},
                    "schema_version": {"bsonType": "int"}
                }
            }
        }
    })

    db["brain_state"].create_index([("_id", 1)], unique=True)
    db["brain_state"].create_index([("updated_at", -1)])

    # ===== 5. UPDATE agent_progress schema =====
    print("Updating agent_progress validator...")
    db.command({
        "collMod": "agent_progress",
        "validator": {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["_id", "task_id", "created_at", "schema_version"],
                "properties": {
                    "_id": {"bsonType": "string"},
                    "task_id": {"bsonType": "string"},
                    "percent_complete": {"bsonType": ["double", "null"], "minimum": 0, "maximum": 100},
                    "checkpoints": {"bsonType": ["array", "null"]},
                    "partial_outputs": {"bsonType": ["object", "null"]},
                    "created_at": {"bsonType": "date"},
                    "updated_at": {"bsonType": "date"},
                    "schema_version": {"bsonType": "int"}
                }
            }
        }
    })

    db["agent_progress"].create_index([("task_id", 1)])
    db["agent_progress"].create_index([("updated_at", -1)])

    # ===== 6. UPDATE agent_runs schema =====
    print("Updating agent_runs validator...")
    db.command({
        "collMod": "agent_runs",
        "validator": {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["_id", "goal_id", "status", "created_at", "schema_version"],
                "properties": {
                    "_id": {"bsonType": "string"},
                    "goal_id": {"bsonType": "string"},
                    "status": {"enum": ["running", "completed", "failed", "cancelled"]},
                    "task_results": {"bsonType": ["array", "null"]},
                    "cost_total": {"bsonType": ["double", "null"], "minimum": 0},
                    "tokens_total": {"bsonType": ["int", "null"], "minimum": 0},
                    "created_at": {"bsonType": "date"},
                    "updated_at": {"bsonType": "date"},
                    "completed_at": {"bsonType": ["date", "null"]},
                    "schema_version": {"bsonType": "int"}
                }
            }
        }
    })

    db["agent_runs"].create_index([("goal_id", 1), ("status", 1)])
    db["agent_runs"].create_index([("status", 1), ("created_at", -1)])

    print("Migration 004 complete:")
    print("  - Renamed agent_objectives → agent_goals")
    print("  - Updated 5 collection schemas (goals, tasks, brain, progress, runs)")
    print("  - Created 10 compound indexes for scheduler queries")


def downgrade(context: dict) -> None:
    """
    Revert migration 004 changes.

    Changes:
    1. Rename agent_goals → agent_objectives
    2. Restore minimal stub validators
    3. Drop new indexes

    Args:
        context: Migration context with mongo dict of databases
    """
    db = context["mongo"]["fingpt_agents"]

    # Restore stub validator
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

    # Drop indexes first
    print("Dropping indexes...")
    for collection_name in ["agent_goals", "agent_tasks", "brain_state", "agent_progress", "agent_runs"]:
        db[collection_name].drop_indexes()

    # Restore stub validators
    print("Restoring stub validators...")
    for collection_name in ["agent_goals", "agent_tasks", "brain_state", "agent_progress", "agent_runs"]:
        db.command({"collMod": collection_name, "validator": stub_validator})

    # Rename back
    print("Renaming agent_goals → agent_objectives...")
    db["agent_goals"].rename("agent_objectives")

    print("Migration 004 downgrade complete")
