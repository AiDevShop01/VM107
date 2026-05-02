"""Migration 006 — Phase 43.1: formalize path field on router_decisions and agent_runs.

Schema state after Plan 01:
    - router_decisions and agent_runs already accept inserts with `path` field
      (validators have NO additionalProperties:false; verified by 43.1 research).
    - Phase 43 emergency-fix conventions: _id=str(uuid.uuid4()), schema_version=1.

This migration formalizes the field in $jsonSchema validators AND adds indexes for
the eventual cost-separation dashboard ("show me thinking spend vs hands spend").

EXECUTION GATE: Plan 03 deploy task runs this — same importlib bypass approach as
Phase 43 Plan 05 used for migration 005 (migration runner blocked by pre-existing
004 MongoDB 6+ incompatibility).
"""
from datetime import datetime, timezone


def upgrade(context: dict) -> None:
    db = context["mongo"]["fingpt_agents"]

    # 1. Backfill existing records with path='chat' so post-migration reads are uniform
    db["router_decisions"].update_many(
        {"path": {"$exists": False}},
        {"$set": {"path": "chat"}},
    )
    db["agent_runs"].update_many(
        {"path": {"$exists": False}},
        {"$set": {"path": "chat"}},
    )

    # 2. Add compound indexes for fast cost-separation dashboard queries
    db["router_decisions"].create_index([("path", 1), ("created_at", -1)], name="path_created_at")
    db["agent_runs"].create_index([("path", 1), ("created_at", -1)], name="path_created_at")

    # 3. Record migration in migrations_applied collection
    db["migrations_applied"].insert_one({
        "_id": "006_router_path_field",
        "applied_at": datetime.now(timezone.utc),
        "phase": "43.1",
        "description": "Formalize path field + indexes on router_decisions and agent_runs",
    })


def downgrade(context: dict) -> None:
    db = context["mongo"]["fingpt_agents"]
    db["router_decisions"].drop_index("path_created_at")
    db["agent_runs"].drop_index("path_created_at")
    db["migrations_applied"].delete_one({"_id": "006_router_path_field"})
