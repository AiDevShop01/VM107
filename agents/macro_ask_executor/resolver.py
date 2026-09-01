"""Phase 155 (155-03) — registry-gated specialist resolver + AZE-07 single dispatch.

Two responsibilities, both fail-loud (§J — never accept-then-silently-ignore, the
SourceHealthRegistry defect class):

  * ``resolve_specialist(agent_id, registry_adapter)`` — validates the dotted id against
    the registry's tagged ``[macro, specialist]`` set, then loads the class by CONVENTION
    (``importlib.import_module(f"agents.{slug}.agent")`` → ``getattr(module, TitleCase)``).
    NO hardcoded id→class dict (§J). Unknown id → ``UnknownSpecialist`` (never None-silent).

  * ``dispatch_specialist(...)`` — wraps one in-process specialist ``.invoke(pillar, ctx)``
    in the AZE-07 ``SubagentResult`` envelope with ``stop_reason`` branching:
      - unknown / out-of-scope id (or unresolved instance) → ``stop_reason="error"`` naming
        the id (capability-checked spoofing guard, T-155-04).
      - missing pillar snapshot / raised specialist → ``stop_reason="error"`` carrying a
        ``confidence=0.0`` sentinel ``SpecialistResponse`` (honest degrade, T-155-09).
      - success → ``stop_reason="completed"`` with the typed ``SpecialistResponse``.

  * ``load_tool_filter(agent_id)`` — reads the specialist's ``allowed_tools`` /
    ``denied_tools`` from ``registry/agent_profile/{agent_id}.yaml`` so the executor's
    ``SubagentRequest.tool_filter`` carries scope through the envelope (moot in-process this
    phase, D-02; Phase-157 enforcement input).

SECURITY (T-155-01): ``diagnostic`` carries the agent id / error-type only — NEVER the JWT
or a raw pillar payload.
"""

from __future__ import annotations

import importlib
import os
from typing import Any

from contracts.economic_intelligence.subagent_contract import SubagentResult
from contracts.economic_intelligence.specialist_response import SpecialistResponse

# ── discovery tags the router/executor gate the 4 pillar analysts by (must_haves truth #2) ──
_SPECIALIST_TAGS: list[str] = ["macro", "specialist"]


class UnknownSpecialist(Exception):
    """Raised when a routed agent_id is not in the registry's tagged specialist set.

    Fail-loud (§J): an out-of-scope id must surface, never be silently skipped.
    """


def _valid_specialist_ids(registry_adapter: Any) -> set[str]:
    rows = registry_adapter.list_capabilities(type="agent_profile", tags=_SPECIALIST_TAGS)
    return {r["id"] for r in rows if r.get("id")}


def resolve_specialist(agent_id: str, registry_adapter: Any) -> object:
    """Return a specialist instance for ``agent_id`` (registry-gated convention load).

    Raises ``UnknownSpecialist`` if the id is absent from the tagged specialist set — the
    fail-loud gate that stops an unknown routed id from being loaded.
    """
    if agent_id not in _valid_specialist_ids(registry_adapter):
        raise UnknownSpecialist(agent_id)

    slug = agent_id.removeprefix("vm107.")  # "vm107.growth_analyst" → "growth_analyst"
    module = importlib.import_module(f"agents.{slug}.agent")
    cls_name = "".join(part.title() for part in slug.split("_"))  # → "GrowthAnalyst"
    cls = getattr(module, cls_name)
    return cls()


def _sentinel_response(agent_id: str) -> SpecialistResponse:
    """A ``confidence=0.0`` sentinel so the synthesizer NAMES the failure in limitations.

    ``answer`` must be non-empty (SpecialistResponse ``min_length=1``); the 0.0 confidence
    is what routes it into ``sections["limitations"]`` (Open Q2 LOCKED).
    """
    return SpecialistResponse(
        answer="<specialist unavailable>",
        confidence=0.0,
        citations=[],
        evidence=[],
        limitations=[f"{agent_id} unavailable"],
        related_entities=[],
    )


def dispatch_specialist(
    agent_id: str,
    instance: object | None,
    pillar: Any | None,
    registry_adapter: Any,
    *,
    context: dict | None = None,
) -> SubagentResult:
    """Dispatch ONE specialist under the AZE-07 envelope, branching on ``stop_reason``."""
    # Capability check — an unknown / out-of-scope id (or an unresolved instance) fails loud.
    if instance is None or agent_id not in _valid_specialist_ids(registry_adapter):
        return SubagentResult(
            output=f"specialist '{agent_id}' is unknown or out of scope",
            structured=None,
            stop_reason="error",
            diagnostic={"agent_id": agent_id, "error": "unknown_or_out_of_scope"},
        )

    # No pillar snapshot (transient miss or a non-pillar routed id) → honest degrade.
    if pillar is None:
        return SubagentResult(
            output="<specialist unavailable>",
            structured=_sentinel_response(agent_id),
            stop_reason="error",
            diagnostic={"agent_id": agent_id, "error": "pillar_unavailable"},
        )

    try:
        response = instance.invoke(pillar, context)  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001 - per-specialist isolation (subscriber.py L212)
        # JWT-free diagnostic: exception TYPE + id only, never the bearer or raw payload.
        return SubagentResult(
            output="<specialist unavailable>",
            structured=_sentinel_response(agent_id),
            stop_reason="error",
            diagnostic={"agent_id": agent_id, "error": type(exc).__name__},
        )

    return SubagentResult(
        output=response.answer,
        structured=response,
        stop_reason="completed",
        diagnostic={"agent_id": agent_id},
    )


# ─────────────────────────────────────────── agent_profile tool-scope (carried-but-moot)


def _profile_path(agent_id: str) -> str:
    here = os.path.dirname(os.path.abspath(__file__))  # agents/macro_ask_executor
    repo_root = os.path.abspath(os.path.join(here, "..", ".."))  # VM107 tree root
    return os.path.join(repo_root, "registry", "agent_profile", f"{agent_id}.yaml")


def load_tool_filter(agent_id: str) -> dict:
    """Return ``{"allowed_tools": [...], "denied_tools": [...]}`` from the agent_profile.

    Missing profile → empty scope (both keys present so the SubagentRequest contract holds).
    """
    path = _profile_path(agent_id)
    profile: dict = {}
    if os.path.exists(path):
        import yaml

        with open(path, encoding="utf-8") as fh:
            profile = yaml.safe_load(fh) or {}
    return {
        "allowed_tools": list(profile.get("allowed_tools") or []),
        "denied_tools": list(profile.get("denied_tools") or []),
    }


__all__ = [
    "UnknownSpecialist",
    "resolve_specialist",
    "dispatch_specialist",
    "load_tool_filter",
]
