"""
curate_task2.py — One-shot Task 2 curation: set impact_on_decision + allowed_agent_profiles.

This script is run once as part of Plan 47.6-00 Task 2. It:

1. Replaces "impact_on_decision: TODO" with the hand-curated HIGH/MEDIUM/LOW value
   for every YAML, using type-based and id-based rules.

2. Sets "allowed_agent_profiles" for tool YAMLs based on tool_scope.HARD_ALLOWED_TOOLS
   (or defaults to [agent_zero] for non-sensitive tools). For non-tool types, sets [].

3. Ensures skill_md_path exists on all skill YAMLs.

LOCK: impact_on_decision values are HAND-CURATED per CONTEXT.md decision #3.
Never auto-generated from docstrings. This script encodes the one-time curation judgment.
"""
from __future__ import annotations

import os
import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
from core.agents.tool_scope import HARD_ALLOWED_TOOLS, SENSITIVE_TOOLS  # noqa: E402

REGISTRY_ROOT = pathlib.Path(os.environ["CAPABILITY_REGISTRY_ROOT"])

# ---------------------------------------------------------------------------
# Tool scope: derive per-tool allowed_agent_profiles from HARD_ALLOWED_TOOLS
# (read direction: for each tool, which agents have it in their allowed set)
# ---------------------------------------------------------------------------
def _build_tool_profiles_map() -> dict[str, list[str]]:
    """Build {tool_name: [agent_ids_that_can_use_it]} from HARD_ALLOWED_TOOLS."""
    result: dict[str, list[str]] = {}
    for agent_id, tools in HARD_ALLOWED_TOOLS.items():
        for tool_name in tools:
            result.setdefault(tool_name, [])
            result[tool_name].append(agent_id)
    # Sort for determinism
    return {k: sorted(v) for k, v in result.items()}


TOOL_PROFILES_MAP = _build_tool_profiles_map()
print("Tool profiles map:", TOOL_PROFILES_MAP)

# ---------------------------------------------------------------------------
# impact_on_decision curation rules
# HIGH: directly drives trade evaluation score, confidence adjustment,
#       behavioral detection, mentor narrative, or replay reconstruction.
# MEDIUM: provides context supporting HIGH-impact reasoning but not score-bearing.
# LOW: developer-facing utilities, debug helpers, visibility-only.
# ---------------------------------------------------------------------------

# Per-type defaults
TYPE_DEFAULT_IMPACT: dict[str, str] = {
    "tool": "HIGH",            # Tools generally drive evaluation
    "signal": "HIGH",          # Signals inform the adaptive loop
    "skill": "HIGH",           # Skills shape narrative quality
    "agent_profile": "HIGH",   # Agent profiles gate capabilities
    "service": "MEDIUM",       # Services are infrastructure
    "event_type": "MEDIUM",    # Events are observability
    "behavioral_pattern": "HIGH",  # Pattern detection is HIGH
    "counterfactual_scenario": "HIGH",  # Counterfactuals drive recommendations
    "replay_template": "MEDIUM",   # Replay templates support context
    "state_machine": "MEDIUM",     # State machines are lifecycle views
    "collection": "MEDIUM",        # Collections are data stores
}

# Per-id overrides (takes priority over type default)
ID_IMPACT_OVERRIDES: dict[str, str] = {
    # TOOLS
    # Core scoring tools (HIGH - directly drive trade evaluation scores)
    "get_trade_quality_score": "HIGH",
    "behavioral_analysis_tool": "HIGH",
    "compression_analysis_tool": "HIGH",
    "execution_quality_tool": "HIGH",
    "liquidity_analysis_tool": "HIGH",
    "regime_analysis_tool": "HIGH",
    "setup_quality_tool": "HIGH",
    "similarity_analysis_tool": "HIGH",
    # Writer tools (HIGH - persist narratives)
    "persist_narrative": "HIGH",
    # Replay tools (HIGH - drives replay reconstruction)
    "fetch_replay_chart_slice_tool": "HIGH",
    "fetch_replay_frame_tool": "HIGH",
    "lookup_replay_artifact_tool": "HIGH",
    # Counterfactual tools (HIGH - drive recommendations)
    "get_counterfactual_tool": "HIGH",
    "get_counterfactuals_for_execution_tool": "HIGH",
    "lookup_counterfactual_scenario_tool": "HIGH",
    # Adaptive intelligence tools (HIGH - drive recommendations and behavioral analysis)
    "get_adaptive_recommendations_tool": "HIGH",
    "get_behavioral_drift_summary_tool": "HIGH",
    "get_behavioral_evolution_tool": "HIGH",
    "get_drift_report_tool": "HIGH",
    "get_pattern_cluster_membership_tool": "HIGH",
    "get_pattern_cluster_stats_tool": "HIGH",
    "get_counterfactual_scenario_stats_tool": "HIGH",
    "get_regime_adaptation_candidates_tool": "HIGH",
    # Cross-trade behavioral tools (HIGH - support behavioral mentor)
    "get_behavioral_edges": "HIGH",
    "get_cross_trade_behavioral_patterns": "HIGH",
    # Reader tools (MEDIUM - context providers)
    "get_primitives": "MEDIUM",   # market data primitive - context provider
    "get_liquidity_context": "MEDIUM",  # context provider for scoring tools
    "get_weekly_execution_summary": "HIGH",  # weekly_review_agent uses this as primary input
    # NOTE: lookup_capability is HIGH because it gates all discovery (per plan note)
    "lookup_capability": "HIGH",

    # SERVICES
    "campaign_service": "HIGH",        # canonical state-transition engine
    "execution_service": "HIGH",       # canonical state-transition engine
    "idea_service": "HIGH",            # canonical state-transition engine
    "mentor_pipeline_orchestrator": "HIGH",   # drives mentor pipeline
    "scope_dispatcher": "HIGH",        # cognition gateway
    "narrative_persister": "HIGH",     # atomic narrative persistence
    "citation_validator": "HIGH",      # hard-fails uncited assertions
    "confidence_vector_calculator": "HIGH",   # computes confidence vector
    "reconstruction_service": "HIGH",  # reconstructs replay state
    "replay_artifact_persister": "HIGH",  # WORM replay persistence
    "replay_narrator": "HIGH",         # produces narrated replay lines
    "adaptive_pipeline_orchestrator": "HIGH",  # weekly adaptive loop
    "execution_mongo_projector": "MEDIUM",  # derived store projection
    "execution_neo4j_projector": "MEDIUM",  # derived store projection
    "execution_qdrant_projector": "MEDIUM",  # derived store projection
    "embedder_service": "MEDIUM",      # embedding infrastructure

    # STATE MACHINES
    "campaign": "HIGH",        # 12-state lifecycle is HIGH (gates downstream)
    "execution": "HIGH",       # 3-state lifecycle is HIGH
    "idea": "LOW",             # 4-state idea lifecycle is visibility-only before trading
    "legacy_status_mapping": "LOW",  # compatibility map is developer-facing

    # COLLECTIONS
    "trade_intelligence": "MEDIUM",  # Qdrant collection - derived store

    # AGENT PROFILES - all HIGH (gate capabilities)
    "agent_zero": "HIGH",
    "idea_agent": "MEDIUM",  # pre-trade ideation, not directly scoring
    "strategy_agent": "MEDIUM",  # strategy analysis, not directly scoring
    "trade_auditor_agent": "HIGH",
    "trade_auditor_agent._reader": "HIGH",
    "trade_auditor_agent._analyzer": "HIGH",
    "trade_auditor_agent._writer": "HIGH",
    "behavioral_mentor_agent": "HIGH",
    "behavioral_mentor_agent._reader": "HIGH",
    "behavioral_mentor_agent._analyzer": "HIGH",
    "behavioral_mentor_agent._writer": "HIGH",
    "weekly_review_agent": "HIGH",
    "weekly_review_agent._reader": "HIGH",
    "weekly_review_agent._analyzer": "HIGH",
    "weekly_review_agent._writer": "HIGH",

    # SKILLS - all HIGH (shape narrative quality directly)
    "citation-discipline": "HIGH",
    "critique-discipline-auditor": "HIGH",
    "critique-discipline-mentor": "HIGH",
    "critique-discipline-weekly": "HIGH",
    "hindsight-discipline": "HIGH",
    "narrative-structure": "HIGH",
    "pattern-recognition-behavioral": "HIGH",
    "pattern-recognition-trade-auditor": "HIGH",
    "pattern-recognition-weekly": "HIGH",
    "adaptive-discipline": "HIGH",

    # SIGNALS - all HIGH (inform adaptive loop)
    "adaptive_recommendation_signal": "HIGH",
    "behavioral_emotional_reactivity_evolution": "HIGH",
    "behavioral_hesitation_evolution": "HIGH",
    "behavioral_premature_exit_evolution": "HIGH",
    "behavioral_rule_deviation_evolution": "HIGH",
    "drift_counterfactual_delta": "HIGH",
    "drift_strategy_category_regime": "HIGH",
    "drift_winrate_calibration": "HIGH",
    "pattern_cluster_signal": "HIGH",

    # BEHAVIORAL PATTERNS - all HIGH (pattern detection drives behavioral scores)
    "fomo_entry": "HIGH",
    "hesitation": "HIGH",
    "late_entry": "HIGH",
    "over_management": "HIGH",
    "revenge_trade": "HIGH",

    # COUNTERFACTUAL SCENARIOS - all HIGH (drive recommendations)
    "counterfactual.entry.bos_confirmation": "HIGH",
    "counterfactual.entry.late_entry_5_bars": "HIGH",
    "counterfactual.entry.wait_for_retest": "HIGH",
    "counterfactual.exit.be_after_1r": "HIGH",
    "counterfactual.exit.mfe_aware_trail": "HIGH",
    "counterfactual.exit.partial_1r": "HIGH",
    "counterfactual.exit.trailing_atr": "HIGH",
    "counterfactual.regime.avoid_news_window": "HIGH",
    "counterfactual.regime.skip_countertrend": "HIGH",
    "counterfactual.regime.skip_low_vol": "HIGH",
    "counterfactual.stop.atr_0_5": "HIGH",
    "counterfactual.stop.atr_1_0": "HIGH",
    "counterfactual.stop.atr_1_5": "HIGH",
    "counterfactual.stop.liquidity_buffer": "HIGH",
    "counterfactual.stop.session_range": "HIGH",

    # REPLAY TEMPLATES - MEDIUM (support replay narrative context)
    "analytics_fanout_completed_replay_template": "MEDIUM",
    "analytics_snapshot_recorded_replay_template": "MEDIUM",
    "campaign_state_transition_replay_template": "MEDIUM",
    "checklist_completed_replay_template": "MEDIUM",
    "execution_state_transition_replay_template": "MEDIUM",
    "fill_received_replay_template": "MEDIUM",
    "idea_state_transition_replay_template": "LOW",
    "order_submitted_replay_template": "MEDIUM",
    "position_closed_replay_template": "HIGH",  # trade outcome - HIGH
    "replay_artifact_generated_replay_template": "MEDIUM",
    "replay_artifact_regenerated_replay_template": "MEDIUM",
    "review_recorded_replay_template": "HIGH",  # review recorded - HIGH

    # EVENT TYPES - mostly MEDIUM (observability); some HIGH where they gate scoring
    "analytics_fanout_completed": "MEDIUM",
    "analytics_snapshot_recorded": "HIGH",  # triggers scoring pipeline
    "analyzer_completed": "MEDIUM",
    "analyzer_failed": "MEDIUM",
    "analyzer_started": "MEDIUM",
    "campaign_state_transition": "HIGH",   # gates analytics trigger
    "checklist_completed": "MEDIUM",
    "constitutional_skill_applied": "MEDIUM",
    "counterfactual_generated_event": "MEDIUM",
    "counterfactual_regenerated_event": "MEDIUM",
    "execution_state_transition": "HIGH",  # gates execution analytics
    "fill_received": "MEDIUM",
    "idea_state_transition": "LOW",
    "mentor_pipeline_completed": "MEDIUM",
    "mentor_pipeline_failed": "MEDIUM",
    "mentor_pipeline_started": "MEDIUM",
    "narrative_envelope_persisted": "HIGH",  # narrative outcome - HIGH
    "narrative_regenerated": "MEDIUM",
    "narrative_regeneration_requested": "MEDIUM",
    "order_submitted": "MEDIUM",
    "position_closed": "HIGH",  # trade outcome - HIGH
    "reader_completed": "MEDIUM",
    "reader_failed": "MEDIUM",
    "reader_started": "MEDIUM",
    "replay_artifact_generated_event": "MEDIUM",
    "replay_artifact_regenerated_event": "MEDIUM",
    "replay_completed": "MEDIUM",
    "replay_requested": "MEDIUM",
    "review_recorded": "HIGH",  # triggers mentor analysis
    "scope_context_injected": "MEDIUM",
    "scope_validation_failed": "HIGH",  # auth failure is HIGH
    "scope_validation_passed": "LOW",  # happy path observability
    "skill_loaded": "LOW",
    "skill_unloaded": "LOW",
    "template_version_bumped": "MEDIUM",
    "writer_completed": "MEDIUM",
    "writer_failed": "MEDIUM",
    "writer_started": "MEDIUM",
}

# ---------------------------------------------------------------------------
# allowed_agent_profiles curation for tool YAMLs
# ---------------------------------------------------------------------------
ALL_MENTOR_PROFILES = [
    "agent_zero",
    "idea_agent",
    "strategy_agent",
    "trade_auditor_agent",
    "trade_auditor_agent._reader",
    "trade_auditor_agent._analyzer",
    "trade_auditor_agent._writer",
    "behavioral_mentor_agent",
    "behavioral_mentor_agent._reader",
    "behavioral_mentor_agent._analyzer",
    "behavioral_mentor_agent._writer",
    "weekly_review_agent",
    "weekly_review_agent._reader",
    "weekly_review_agent._analyzer",
    "weekly_review_agent._writer",
]


def get_tool_profiles(tool_id: str, current_profiles: list) -> list[str]:
    """Determine allowed_agent_profiles for a tool YAML.

    - If tool is in SENSITIVE_TOOLS: use TOOL_PROFILES_MAP (agents that have it)
    - Otherwise (non-sensitive/soft tool): use [agent_zero] as default per plan,
      OR if profiles already set (not from normalize TODO), preserve them.
    """
    tool_name = tool_id  # tool id == tool name in this registry

    if tool_name in SENSITIVE_TOOLS:
        # Use the agents that explicitly have this tool in HARD_ALLOWED_TOOLS
        profiles = TOOL_PROFILES_MAP.get(tool_name, [])
        return sorted(profiles)
    else:
        # Non-sensitive tool — if already curated with specific profiles, keep them
        # If empty or generic [agent_zero] default, keep [agent_zero]
        if current_profiles and current_profiles != ["agent_zero"]:
            return sorted(set(current_profiles))
        return ["agent_zero"]


def load_yaml(path: pathlib.Path) -> dict:
    """Load first document from YAML file."""
    raw = path.read_text(encoding="utf-8")
    docs = list(yaml.safe_load_all(raw))
    return next((d for d in docs if d is not None and isinstance(d, dict)), {})


def save_yaml(path: pathlib.Path, data: dict) -> None:
    """Save YAML atomically."""
    tmp = path.with_suffix(".yaml.tmp")
    serialized = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False)
    tmp.write_text(serialized, encoding="utf-8")
    os.replace(tmp, path)


def curate_yaml(path: pathlib.Path) -> tuple[bool, list[str]]:
    """Apply Task 2 curation to one YAML. Returns (changed, [changes])."""
    rel = path.relative_to(REGISTRY_ROOT)
    parts = rel.parts
    type_folder = parts[0] if len(parts) >= 2 else "unknown"

    data = load_yaml(path)
    if not data:
        return False, [f"SKIP: empty document"]

    changes: list[str] = []

    yaml_id = data.get("id", path.stem)

    # 1. Set impact_on_decision
    current_impact = data.get("impact_on_decision")
    if current_impact == "TODO" or current_impact not in {"HIGH", "MEDIUM", "LOW"}:
        # Look up the curated value
        new_impact = ID_IMPACT_OVERRIDES.get(yaml_id) or TYPE_DEFAULT_IMPACT.get(type_folder, "MEDIUM")
        data["impact_on_decision"] = new_impact
        changes.append(f"impact_on_decision: TODO -> {new_impact}")

    # 2. Set allowed_agent_profiles
    current_profiles = data.get("allowed_agent_profiles", [])
    if type_folder == "tool":
        new_profiles = get_tool_profiles(yaml_id, current_profiles or [])
        if new_profiles != (current_profiles or []):
            data["allowed_agent_profiles"] = new_profiles
            changes.append(f"allowed_agent_profiles: {current_profiles} -> {new_profiles}")
    elif not current_profiles and type_folder not in ("tool",):
        # Non-tool types: [] means no profile restriction (visible to all per stage 5 semantics)
        # Keep as [] if already [] (already set by normalize)
        pass

    # 3. Skill: ensure skill_md_path
    if type_folder == "skill":
        skill_id = yaml_id  # e.g., "citation-discipline"
        expected_path = f"VM107/skills/{skill_id}/SKILL.md"
        if "skill_md_path" not in data:
            data["skill_md_path"] = expected_path
            changes.append(f"skill_md_path: MISSING -> {expected_path}")
        else:
            existing = data["skill_md_path"]
            # skill_md_path is relative to FinGPT root (parent of VM107)
            fingpt_root = REGISTRY_ROOT.parent.parent
            if not (fingpt_root / existing).exists():
                # path doesn't resolve - fix to expected
                data["skill_md_path"] = expected_path
                changes.append(f"skill_md_path: {existing} -> {expected_path} (old path unresolvable)")

    if changes:
        save_yaml(path, data)

    return bool(changes), changes


def main():
    yaml_paths = sorted(REGISTRY_ROOT.rglob("*.yaml"))
    total = len(yaml_paths)
    changed_count = 0
    errors = []

    print(f"Curating {total} YAMLs under {REGISTRY_ROOT}")
    for path in yaml_paths:
        try:
            changed, changes = curate_yaml(path)
            rel = path.relative_to(REGISTRY_ROOT)
            if changed:
                changed_count += 1
                print(f"  CURATED: {rel}")
                for c in changes:
                    print(f"    - {c}")
        except Exception as exc:
            errors.append((path, str(exc)))
            print(f"  ERROR: {path.relative_to(REGISTRY_ROOT)}: {exc}")

    print()
    print(f"Summary:")
    print(f"  Total:   {total}")
    print(f"  Changed: {changed_count}")
    print(f"  Errors:  {len(errors)}")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
