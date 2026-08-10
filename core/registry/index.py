"""LD-4 index slicing — profile-scoped capability index.

get_index_for_profile returns the subset of capabilities that a given
agent profile is allowed to access, filtered to:
  - status == REAL
  - profile_id in allowed_agent_profiles (or base profile matches sub-profile)
  - deprecated == False

The result is a lightweight list of dicts suitable for injection into an
agent's cognition context without exposing full YAML payloads.
"""

from __future__ import annotations

from fingpt_core.contracts.capability_registry import (
    CapabilityRegistrySnapshot,
    CapabilityStatus,
)


def get_index_for_profile(
    snapshot: CapabilityRegistrySnapshot,
    profile_id: str,
    descriptions: dict[str, str] | None = None,
) -> list[dict]:
    """Return the LD-4 index slice for a given agent profile.

    Args:
        snapshot: The frozen registry snapshot.
        profile_id: The agent profile id to filter for.
        descriptions: Optional dict(capability_id -> short_description) side channel.
            CapabilitySnapshotEntry does not include short_description (it's a
            CapabilitySummary field). Pass the loader side channel to populate it.

    Returns:
        List of dicts with keys: id, short_description, impact_on_decision.
        Only real, non-deprecated, profile-allowed entries are included.
    """
    if descriptions is None:
        descriptions = {}

    result = []
    for e in snapshot.entries:
        if e.status != CapabilityStatus.REAL:
            continue
        if e.deprecated:
            continue
        # Profile matching — mirrors is_capability_in_scope() logic exactly.
        # hard_scoped=True: exact match only (no base-profile fallback).
        # hard_scoped=False: exact match OR base-id match for sub-profiles.
        #
        # D-01 (Phase 137, E-CRIT1): empty allowed_agent_profiles = ZERO grantees
        # (fail-closed). A tool must be EXPLICITLY granted to a profile to be
        # advertised. This is now at PARITY with
        # capability_registry.is_capability_in_scope (lines 292-297), which already
        # returns False on an empty list. Previously an empty list meant allow-all
        # here — the E-CRIT1 advertising-vs-authorization divergence bug.
        allowed = False
        if not e.allowed_agent_profiles:
            # Fail-closed: an empty allowed_agent_profiles advertises to nobody.
            # Mirror is_capability_in_scope's deny — skip this entry entirely.
            continue
        elif e.hard_scoped:
            # Exact match only — base profile cannot inherit a hard-scoped capability.
            allowed = profile_id in e.allowed_agent_profiles
        else:
            base_of_caller = profile_id.split(".")[0]
            for listed_profile in e.allowed_agent_profiles:
                if listed_profile == profile_id:
                    allowed = True
                    break
                # Sub-profile slot: "agent_zero" matches "agent_zero._writer" etc.
                if listed_profile.startswith(profile_id + "."):
                    allowed = True
                    break
                # Caller is a sub-profile: "agent_zero._writer" → base is "agent_zero"
                if listed_profile == base_of_caller:
                    allowed = True
                    break
        if not allowed:
            continue

        result.append({
            "id": e.id,
            "short_description": descriptions.get(e.id, ""),
            "impact_on_decision": e.impact_on_decision.value,
        })

    return result
