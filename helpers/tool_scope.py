"""helpers/tool_scope.py — Pure-function tool-scope filter.

Phase 89.1 Plan 03 (REQ-89-9.3): implements the allowed_tools / denied_tools
filter contract for agent profiles.

Key design points:
  - No agent / Flask / Dagster dependencies — safe for direct unit testing.
  - Type-preserving: accepts and returns list[str], list[dict], or dict[str, Any].
  - For list[dict] inputs, the tool name is read from entry["id"] (CapabilityRegistry
    index shape).
  - Missing tools (in allowed but absent from available) are silently skipped.
  - deny wins on collision when both allowed and denied are provided.

Public API:
    apply_tool_scope(available_tools, allowed, denied) -> same type as available_tools
"""
from __future__ import annotations

from typing import Any


def apply_tool_scope(
    available_tools: list[str] | list[dict] | dict[str, Any],
    allowed: list[str] | None,
    denied: list[str] | None,
) -> list[str] | list[dict] | dict[str, Any]:
    """Filter the available tool registry per profile scope rules.

    Rules:
      - allowed=None AND denied=None → return available_tools UNCHANGED.
      - allowed=[...] → return tools whose names appear in ``allowed``
        (others dropped).
      - denied=[...] → return tools whose names do NOT appear in ``denied``.
      - Both set → first restrict to allowed, then strip denied (deny wins
        on collision — defensive default).
      - Tool names not present in available_tools (e.g., optional
        search_macro_research when Phase 92 isn't shipped) are silently
        skipped (no KeyError / no error).

    Type-preserving:
      - list[str] in → list[str] out
      - list[dict] in (each dict has "id" key, e.g., CapabilityRegistry
        index entries) → list[dict] out (matched by entry["id"])
      - dict[str, Any] in → dict[str, Any] out (matched by key)

    Args:
        available_tools: The full tool registry as returned by the caller.
            Accepts three shapes: list[str], list[dict] (with "id" key),
            or dict[str, Any] (tool name as key).
        allowed: Whitelist of tool names to retain.  ``None`` means "no
            whitelist — keep all".
        denied: Blacklist of tool names to strip.  ``None`` means "no
            blacklist — strip nothing".

    Returns:
        Filtered tool registry in the same type as ``available_tools``.
    """
    if not allowed and not denied:
        return available_tools

    # --- dict[str, Any] branch ---
    if isinstance(available_tools, dict):
        result: dict[str, Any] = dict(available_tools)
        if allowed is not None:
            allowed_set = set(allowed)
            result = {k: v for k, v in result.items() if k in allowed_set}
        if denied is not None:
            denied_set = set(denied)
            result = {k: v for k, v in result.items() if k not in denied_set}
        return result

    # --- list branch (str or dict entries) ---
    if isinstance(available_tools, list):
        if _is_index_entries(available_tools):
            # list[dict] with "id" key (CapabilityRegistry index shape)
            return _filter_index_entries(available_tools, allowed, denied)
        else:
            # list[str]
            return _filter_str_list(available_tools, allowed, denied)

    # Fallback: return unchanged for unrecognised types (defensive)
    return available_tools


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _is_index_entries(items: list) -> bool:
    """Return True if the list looks like CapabilityRegistry index entries (list[dict])."""
    if not items:
        return False
    return isinstance(items[0], dict)


def _filter_str_list(
    tools: list[str],
    allowed: list[str] | None,
    denied: list[str] | None,
) -> list[str]:
    result = list(tools)
    if allowed is not None:
        allowed_set = set(allowed)
        result = [t for t in result if t in allowed_set]
    if denied is not None:
        denied_set = set(denied)
        result = [t for t in result if t not in denied_set]
    return result


def _filter_index_entries(
    entries: list[dict],
    allowed: list[str] | None,
    denied: list[str] | None,
) -> list[dict]:
    result = list(entries)
    if allowed is not None:
        allowed_set = set(allowed)
        result = [e for e in result if e.get("id") in allowed_set]
    if denied is not None:
        denied_set = set(denied)
        result = [e for e in result if e.get("id") not in denied_set]
    return result
