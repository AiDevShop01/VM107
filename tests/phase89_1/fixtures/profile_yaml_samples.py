"""Phase 89.1 Plan 03 — Profile YAML fixture samples for tool-scope filter tests.

Three profile shapes and three tool-list shapes mirroring the real macro_investigator
registry YAML and the CapabilityRegistry index entry format.

Fixture catalogue:
  PROFILE_MACRO_INVESTIGATOR_DICT  — full dict with allowed_tools + denied_tools
  PROFILE_LEGACY_STRING            — plain string ("default") for backward-compat
  PROFILE_BARE_DICT                — dict without allowed_tools / denied_tools keys
  AVAILABLE_TOOLS_LIST             — list[str] shape (7 tool names)
  AVAILABLE_TOOLS_DICT             — dict shape: {name: {"description": "..."}}
  AVAILABLE_TOOLS_INDEX_ENTRIES    — list[dict] matching CapabilityRegistry index shape
"""

# ---------------------------------------------------------------------------
# 7 tool names shared across all three AVAILABLE_TOOLS_* fixtures
# ---------------------------------------------------------------------------

_ALL_TOOL_NAMES = [
    "code_execution_tool",
    "text_editor",
    "search_knowledge",
    "vm102.indicator_history",
    "vm105.neo4j_macro_graph_walker",
    "episodic_memory_service.query",
    "belief_store.query",
]

# ---------------------------------------------------------------------------
# Profile fixtures
# ---------------------------------------------------------------------------

PROFILE_MACRO_INVESTIGATOR_DICT: dict = {
    "id": "vm107.macro_investigator",
    "type": "agent_profile",
    "status": "real",
    "b5_self_eval": True,
    "allowed_tools": [
        "vm102.indicator_history",
        "vm105.neo4j_macro_graph_walker",
        "episodic_memory_service.query",
        "belief_store.query",
        "search_macro_research",  # OPTIONAL — may be absent in available registry
    ],
    "denied_tools": [
        "code_execution_tool",
        "text_editor",
        "search_knowledge",
    ],
}

PROFILE_LEGACY_STRING: str = "default"

PROFILE_BARE_DICT: dict = {
    "id": "vm107.minimal_agent",
    "type": "agent_profile",
    "status": "real",
    "b5_self_eval": False,
    # No allowed_tools / denied_tools keys
}

# ---------------------------------------------------------------------------
# Available-tool list fixtures
# ---------------------------------------------------------------------------

AVAILABLE_TOOLS_LIST: list[str] = list(_ALL_TOOL_NAMES)

AVAILABLE_TOOLS_DICT: dict = {
    name: {"description": f"Tool {name!r} — stub description for tests"}
    for name in _ALL_TOOL_NAMES
}

AVAILABLE_TOOLS_INDEX_ENTRIES: list[dict] = [
    {
        "id": name,
        "short_description": f"Stub short description for {name}",
        "impact_on_decision": "MEDIUM",
    }
    for name in _ALL_TOOL_NAMES
]
