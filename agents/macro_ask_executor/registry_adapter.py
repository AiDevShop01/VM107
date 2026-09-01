"""Phase 155 (155-03) — CapabilityRegistry adapter for the macro-ask fan-out executor.

Thin object exposing ``list_capabilities(*, type=None, tags=None) -> list[dict]`` over the
Phase 47.6 ``CapabilityRegistry`` so the SAME instance can be handed to BOTH
``MacroAskRouter(capability_registry=...)`` (which needs the
``CapabilityRegistryProtocol`` shape — ``conversation_planner.py`` L53-62) AND the
registry-gated ``resolve_specialist`` (which needs ``{r["id"] ...}`` rows).

The module-level ``tools.lookup_capability.list_capabilities`` is a free function (NOT a
bound method), so it cannot be passed where the router expects an object with a
``list_capabilities`` method. This adapter wraps it into that object shape and normalises
the ``ListResult`` summaries into plain ``{"id", "type"}`` dicts.
"""

from __future__ import annotations

from typing import Any


def _normalise(entry: Any) -> dict:
    """Coerce a registry summary (object or dict) into a ``{"id", "type"}`` row."""
    if isinstance(entry, dict):
        return {"id": entry.get("id"), "type": entry.get("type")}
    type_val = getattr(entry, "type", None)
    # CapabilityType enums carry ``.value``; keep the plain string for callers.
    type_str = getattr(type_val, "value", type_val)
    return {"id": getattr(entry, "id", None), "type": type_str}


class RegistryAdapter:
    """Object-shaped wrapper over ``tools.lookup_capability.list_capabilities``.

    Satisfies ``agents.macro_ask_router.conversation_planner.CapabilityRegistryProtocol``
    so it can drive the router, and yields ``{"id": ...}`` rows so it can gate the resolver.
    """

    def list_capabilities(
        self,
        *,
        type: str | None = None,  # noqa: A002 - mirror the registry API keyword
        tags: list[str] | None = None,
    ) -> list[dict]:
        # Imported lazily so importing this module never forces the whole registry to load
        # (keeps the unit suite, which injects a stub registry, import-cheap).
        from tools.lookup_capability import list_capabilities as _list_capabilities

        result = _list_capabilities(type=type, tags=tags)
        entries = getattr(result, "capabilities", result)
        return [_normalise(e) for e in entries]


__all__ = ["RegistryAdapter"]
