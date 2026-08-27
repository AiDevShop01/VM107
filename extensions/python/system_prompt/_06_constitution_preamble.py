"""Phase 167 Plan 02 (AGV-02) — Constitution preamble system_prompt extension.

Injects the single, versioned 19-rule Agent Constitution as ONE inherited
``system_prompt`` preamble when the agent's profile carries ``constitutional_skills``,
and no-ops otherwise — mirroring ``_05_tool_scope_filter``'s zero-blast-radius
discipline (three guards: string profile / dict-without-key / no agent).

Chain order (numbered): ``_05_tool_scope_filter`` -> ``_06_constitution_preamble`` ->
``_10_main_prompt`` -> ``_11_tools_prompt`` -> ...  The ``_06_`` slot places the
constitutional rules AFTER tool-scope filtering and BEFORE the main prompt body, so
the rules land ahead of the agent's individual instructions.

Single versioned source (governance guarantee T-167-03): the preamble text derives
from ``Documentation/Agent Zero/agent-catalogue/02-AGENT-CONSTITUTION.md``, assembled
ONCE in ``render_constitution_preamble()``. There is no per-agent text override — an
agent can only opt out by lacking ``constitutional_skills`` (which the 167-01 lint
parity check surfaces). The preamble is prose-only and never mutates
``allowed_tools`` / ``denied_tools`` (T-167-04): ``_05_tool_scope_filter``, which runs
earlier, remains the sole tool-scope enforcement point.

AGV-02 builds the preamble ON the already-shipped ``constitutional_skills`` profile
field (35 profiles carry it, boot-validated at Phase 60), NOT a parallel mechanism.
"""
from __future__ import annotations

from typing import Any

from helpers.extension import Extension
from agent import Agent, LoopData  # noqa: F401  (Agent kept for parity with _05 signature imports)


# The 19 rules — short-form, verbatim from 02-AGENT-CONSTITUTION.md "The 19 rules".
# A single module-level versioned constant assembled ONCE (no per-rule loop into the
# system_prompt list that could duplicate the block). Editing the Constitution means
# editing the catalogue source and this constant together — it is not per-agent tunable.
_CONSTITUTION_RULES: tuple[str, ...] = (
    "Never fabricate unavailable data.",
    "Deterministic evidence outranks LLM inference.",
    "State freshness must always be checked.",
    "Separate fact from inference.",
    "Provide evidence for material claims.",
    "Explicitly identify contradictions.",
    "State important assumptions.",
    "State missing information.",
    "Never convert uncertainty into certainty.",
    "Historical analogy is not proof.",
    "Correlation is not causation.",
    "Never recommend a trade purely from narrative.",
    "Always identify thesis invalidation.",
    "Respect authority boundaries.",
    "Persist significant conclusions.",
    (
        "Prefer determinism over inference — do not use an LLM to derive information a "
        "deterministic FINgpt capability can economically and reliably provide."
    ),
    "Minimum sufficient state; disclose progressively.",
    "Point-in-time truth — no look-ahead; reason only with information available at the time analysed.",
    "Provenance & memory integrity — never let FINgpt cite FINgpt as fact.",
)

_CONSTITUTION_HEADER = (
    "# The FINgpt Agent Constitution\n"
    "These rules are inherited by every FINgpt agent, above your individual "
    "instructions. They are invariants that make agent output trustworthy — do not "
    "restate or override them; comply with them.\n"
    "Source of truth: Documentation/Agent Zero/agent-catalogue/02-AGENT-CONSTITUTION.md"
)


def render_constitution_preamble(skills: Any = None) -> str:
    """Return the single, versioned Constitution preamble as ONE string.

    The 19-rule body is the module-level ``_CONSTITUTION_RULES`` constant, assembled
    once here — it cannot be per-agent edited (governance guarantee T-167-03).

    ``skills`` (the profile's ``constitutional_skills`` list) is acknowledged for
    traceability in a trailing line only; it never alters the rule text. Output is
    deterministic for a given ``skills`` value.
    """
    numbered = "\n".join(
        f"{i}. {rule}" for i, rule in enumerate(_CONSTITUTION_RULES, start=1)
    )
    parts = [_CONSTITUTION_HEADER, "", numbered]
    if skills:
        try:
            active = ", ".join(str(s) for s in skills)
        except TypeError:
            active = str(skills)
        parts.extend(["", f"Active constitutional skills: {active}"])
    return "\n".join(parts)


class ConstitutionPreamble(Extension):
    """system_prompt extension — injects the inherited Constitution preamble.

    Numbered ``_06_`` so it runs AFTER ``_05_tool_scope_filter`` and BEFORE
    ``_10_main_prompt`` in the numerical extension chain. Active only when
    ``agent.profile`` is a dict carrying ``constitutional_skills``; all other agents
    pass through unchanged (zero blast radius on legacy agents), mirroring ``_05``'s
    three no-op guards exactly.
    """

    async def execute(
        self,
        system_prompt: list[str] = [],
        loop_data: LoopData = LoopData(),
        **kwargs: Any,
    ):
        agent = self.agent
        # Agent.profile is not always surfaced as an attribute (older base images);
        # use getattr to match the safe pattern in _05_tool_scope_filter / agent.py.
        profile = getattr(agent, "profile", None) if agent else None
        if not isinstance(profile, dict):
            return  # legacy string profile or no agent → no-op (zero blast radius)

        skills = profile.get("constitutional_skills")
        if not skills:
            return  # bare dict without constitutional_skills → explicit no-op

        # Single versioned source — inserted ONCE at the head of the prompt so the
        # constitutional rules precede the agent's individual instructions.
        system_prompt.insert(0, render_constitution_preamble(skills))

        agent.context.log.log(
            type="system_prompt",
            content=f"constitution_preamble injected skills={len(skills)}",
        )
