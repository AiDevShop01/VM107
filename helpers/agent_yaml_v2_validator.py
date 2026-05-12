"""Boot-time validator for agent.yaml v2 profiles — CTX-§7.

Raises hard errors on missing or malformed v2 fields so that invalid profiles
fail at startup rather than silently propagating None defaults at runtime.

v1 profiles (schema_version=None) are grandfathered with a deprecation warning
until backfilled in Plan 60-12 (all legacy profiles get v2 fields).

Usage:
    from helpers.agent_yaml_v2_validator import validate_agent_yaml_v2
    subagent = SubAgent.model_validate(yaml_data)
    validate_agent_yaml_v2(profile_name, subagent)   # raises or returns None

Exports: validate_agent_yaml_v2, AgentYamlV2Error, ScopeSpecValidationError,
         is_v2_profile
"""
from __future__ import annotations

import importlib
import logging
import warnings
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from helpers.subagents import SubAgent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Allowed ScopeSpec field values — CONTEXT.md §5
# ---------------------------------------------------------------------------

ALLOWED_ACCOUNT_SCOPE = {"required", "NONE"}
ALLOWED_NARRATIVE_VISIBILITY = {"NONE", "PRIOR_ONLY", "FULL"}
ALLOWED_CROSS_TRADE_VISIBILITY = {"NONE", "ACCOUNT_SCOPED"}
ALLOWED_EXECUTION_SCOPE = {"required", "NONE"}

_SCOPE_SPEC_FIELD_RULES: dict[str, set[str]] = {
    "account_scope": ALLOWED_ACCOUNT_SCOPE,
    "narrative_visibility": ALLOWED_NARRATIVE_VISIBILITY,
    "cross_trade_visibility": ALLOWED_CROSS_TRADE_VISIBILITY,
    "execution_scope": ALLOWED_EXECUTION_SCOPE,
}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class AgentYamlV2Error(ValueError):
    """Raised when a v2 agent.yaml profile fails boot-time validation.

    CTX-§7: Any v2 profile that fails this validator must NOT be loaded —
    it indicates a malformed profile that would silently misbehave at runtime.
    """


class ScopeSpecValidationError(AgentYamlV2Error):
    """Raised when memory_scope contains an invalid field value.

    Subclass of AgentYamlV2Error so callers can catch either.
    """


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_v2_profile(agent: "SubAgent") -> bool:
    """Return True if this agent.yaml is a Phase 60 v2 profile.

    v1 profiles have schema_version=None (legacy — grandfathered until 60-12).
    """
    return getattr(agent, "schema_version", None) == 2


def validate_agent_yaml_v2(profile_name: str, agent: "SubAgent") -> None:
    """Validate a SubAgent instance against Phase 60 v2 schema rules.

    Called after SubAgent.model_validate() — Pydantic type validation has
    already run; this function applies semantic rules on top of it.

    v1 profiles (schema_version=None) skip validation with a deprecation
    warning.  Any v2 schema violation raises AgentYamlV2Error (or its
    subclass ScopeSpecValidationError) immediately — callers must not catch
    and swallow these errors.

    Args:
        profile_name: Human-readable profile name for error messages.
        agent: The already-Pydantic-validated SubAgent instance.

    Raises:
        AgentYamlV2Error: profile violates v2 schema rules.
        ScopeSpecValidationError: memory_scope contains invalid field values.
    """
    schema_version = getattr(agent, "schema_version", None)

    # --- v1 fast-path: grandfathered profiles skip validation ---
    if schema_version is None:
        warnings.warn(
            f"[v1 deprecated] Profile '{profile_name}' has no schema_version. "
            "v1 profiles are grandfathered until Phase 60-12 backfill. "
            "Set schema_version: 2 and add required v2 fields to suppress this warning.",
            DeprecationWarning,
            stacklevel=2,
        )
        return

    # --- Unsupported schema_version ---
    if schema_version != 2:
        raise AgentYamlV2Error(
            f"Profile '{profile_name}': unsupported schema_version {schema_version!r}; "
            "expected 2. Only schema_version: 2 is supported in Phase 60."
        )

    # --- constitutional_skills: if non-empty, must include 'citation-discipline' ---
    # CTX-§8: Phase 60 MENTOR profiles that declare constitutional_skills must include
    # citation-discipline. Non-mentor v2 profiles (e.g. strategy_agent, idea_agent)
    # may declare an empty list [] to indicate "no constitutional skills" — this is
    # valid. Only profiles with a non-empty constitutional_skills list that OMITS
    # citation-discipline are rejected (they claim to have constitutional rules but
    # skipped the citation requirement).
    constitutional = getattr(agent, "constitutional_skills", None)
    if constitutional is None:
        # constitutional_skills field is absent entirely — treat same as missing field
        # for v2 profiles that should declare it explicitly (even as empty []).
        pass  # Not a hard-fail; allows profiles without the field to still load.
    elif constitutional and "citation-discipline" not in constitutional:
        # Non-empty list that omits citation-discipline is a policy violation.
        raise AgentYamlV2Error(
            f"Profile '{profile_name}': constitutional_skills is non-empty but does "
            "not include 'citation-discipline' (CTX-§8). All Phase 60 mentor profiles "
            "that declare constitutional skills must include citation-discipline. "
            f"Got: {constitutional!r}"
        )
    # Empty list [] is valid — non-mentor v2 profiles explicitly declare no constitutional skills.

    # --- memory_scope must be present and valid ---
    memory_scope = getattr(agent, "memory_scope", None)
    if memory_scope is None:
        raise AgentYamlV2Error(
            f"Profile '{profile_name}': memory_scope is required for v2 profiles "
            "(CTX-§5). Set at minimum: account_scope: required or NONE."
        )

    _validate_memory_scope(profile_name, memory_scope)

    # --- input_contract / output_contract — import path must be resolvable ---
    for field_name in ("input_contract", "output_contract"):
        dotted_path = getattr(agent, field_name, None)
        if dotted_path:
            _validate_import_path(profile_name, field_name, dotted_path)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _validate_memory_scope(profile_name: str, memory_scope: dict) -> None:
    """Validate memory_scope dict against CONTEXT.md §5 allowed values.

    Only validates keys that are PRESENT — absence of an optional key is
    not an error (the profile may omit cross_trade_visibility if not needed).
    """
    for field, allowed_values in _SCOPE_SPEC_FIELD_RULES.items():
        if field not in memory_scope:
            continue
        value = memory_scope[field]
        if value not in allowed_values:
            raise ScopeSpecValidationError(
                f"Profile '{profile_name}': memory_scope.{field} = {value!r} is not "
                f"a valid value. Allowed: {sorted(allowed_values)!r}. "
                "(CTX-§5 ScopeSpec)"
            )


def _validate_import_path(profile_name: str, field_name: str, dotted_path: str) -> None:
    """Attempt to import the module and get the class attribute from a dotted path.

    E.g. "fingpt_core.contracts.narrative.NarrativeEnvelope" →
         import fingpt_core.contracts.narrative; getattr(..., "NarrativeEnvelope")

    Raises AgentYamlV2Error if either the module import or the attribute lookup fails.
    """
    # Split at last '.' to separate module from class
    if "." not in dotted_path:
        raise AgentYamlV2Error(
            f"Profile '{profile_name}': {field_name} = {dotted_path!r} is not a "
            "valid dotted import path (expected 'module.ClassName' format)."
        )

    module_path, _, attr_name = dotted_path.rpartition(".")

    try:
        mod = importlib.import_module(module_path)
    except ImportError as exc:
        raise AgentYamlV2Error(
            f"Profile '{profile_name}': {field_name} = {dotted_path!r} — "
            f"cannot import module '{module_path}': {exc}"
        ) from exc

    if not hasattr(mod, attr_name):
        raise AgentYamlV2Error(
            f"Profile '{profile_name}': {field_name} = {dotted_path!r} — "
            f"module '{module_path}' has no attribute '{attr_name}'."
        )
