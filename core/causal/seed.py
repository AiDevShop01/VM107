"""Phase 170 Plan 02 (D-03) — deterministic, reuse-first seed for the registry.

`build_registry()` reads every real `vm107.*_domain_analyst.yaml`
`domain_definition:` block shipped by 169 and emits one `MechanismRecord` per
`claim_template` that carries a subject/predicate. The registered `mechanism`
text is drawn REUSE-FIRST from that domain's `signal_roles.lead/lag` plus the
template's `invalidation_conditions` / `assumptions` — never invented free-form
(engine-lock D-02, D-03).

Discipline mirrored from `core/agents/domain_definition.py::from_profile` (169):
- **safe_load ONLY (ASVS V5 / T-170-02-01).** Every profile is parsed via
  `yaml.safe_load` — never `yaml.load`.
- **Fragile-tree floor (T-170-02-01).** A malformed / non-mapping / underscore-
  scaffold block is skipped (collected, never raised) — the seed never bricks.
- **Determinism-first (T-170-02-03).** Sorted glob + stable per-template record
  order => a reproducible `registry_version` content hash. No wall-clock, no LLM.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from core.agents.domain_definition import ClaimTemplate, DomainDefinition, SignalRoles
from core.causal.mechanism_registry import CausalMechanismRegistry, MechanismRecord

_PROFILE_GLOB = "vm107.*_domain_analyst.yaml"
_NAME_PREFIX = "vm107."
_NAME_SUFFIX = "_domain_analyst.yaml"


def _domain_from_filename(name: str) -> str:
    """Derive the domain slug from a profile filename.

    `vm107.inflation_domain_analyst.yaml` -> `inflation`;
    `vm107.monetary_policy_domain_analyst.yaml` -> `monetary_policy`.
    """
    stem = name
    if stem.startswith(_NAME_PREFIX):
        stem = stem[len(_NAME_PREFIX):]
    if stem.endswith(_NAME_SUFFIX):
        stem = stem[: -len(_NAME_SUFFIX)]
    return stem


def _derive_mechanism(
    signal_roles: SignalRoles, template: ClaimTemplate, domain: str
) -> str:
    """Build the transmission-mechanism text REUSE-FIRST from real block fields.

    Draws from the domain's lead/lag signal roles and the template's own
    invalidation_conditions + assumptions (D-03 — do NOT invent from scratch).
    Falls back to a minimal, still-grounded description if a template carries
    none of those, so the frozen `mechanism` field is always non-empty.
    """
    parts: list[str] = []
    if signal_roles.lead:
        parts.append("transmits via lead signals " + ", ".join(signal_roles.lead))
    if signal_roles.lag:
        parts.append("confirmed by lag signals " + ", ".join(signal_roles.lag))
    if template.invalidation_conditions:
        parts.append("invalidated when " + "; ".join(template.invalidation_conditions))
    if template.assumptions:
        parts.append("assuming " + "; ".join(template.assumptions))
    if not parts:
        parts.append(
            f"{template.subject} {template.predicate} within the {domain} domain "
            f"(mechanism seeded from its domain_definition)"
        )
    return " | ".join(parts)


def build_registry(
    profile_dir: str | Path = "registry/agent_profile",
) -> CausalMechanismRegistry:
    """Seed a `CausalMechanismRegistry` from the real 169 domain_definition blocks.

    Globs `vm107.*_domain_analyst.yaml` under ``profile_dir`` (sorted for
    determinism), `yaml.safe_load`s each (safe_load ONLY — ASVS V5), validates
    the `domain_definition:` block via `DomainDefinition.from_profile`, and emits
    one `MechanismRecord` per claim_template carrying a subject/predicate. A
    malformed / non-mapping / underscore-scaffold profile is skipped, never
    raised (fragile-tree floor). Deterministic + LLM-free.
    """
    directory = Path(profile_dir)
    records: list[MechanismRecord] = []
    skipped: list[str] = []

    for path in sorted(directory.glob(_PROFILE_GLOB)):
        domain = _domain_from_filename(path.name)
        # Leading-underscore scaffold domain (e.g. vm107._scaffold_domain_analyst.yaml)
        # is a template, not a shippable domain — skip (mirror the 169 loader convention).
        if not domain or domain.startswith("_"):
            skipped.append(f"{path.name}: scaffold/template")
            continue
        try:
            data = yaml.safe_load(path.read_text())  # safe_load ONLY — ASVS V5
            if not isinstance(data, dict) or "domain_definition" not in data:
                skipped.append(f"{path.name}: no domain_definition: mapping")
                continue
            definition = DomainDefinition.from_profile(data)  # typed + validated (reuse-first)
        except Exception as exc:  # malformed block => skip, never brick the seed
            skipped.append(f"{path.name}: {type(exc).__name__}: {exc}")
            continue

        signal_roles = definition.signal_roles
        for template in definition.reasoning_rules.claim_templates:
            subject = (template.subject or "").strip()
            predicate = (template.predicate or "").strip()
            if not subject or not predicate:
                continue
            records.append(
                MechanismRecord(
                    domain=domain,
                    claim_class=template.claim_class,
                    subject=subject,
                    predicate=predicate,
                    mechanism=_derive_mechanism(signal_roles, template, domain),
                    version=definition.version,
                )
            )

    return CausalMechanismRegistry(records=tuple(records))


__all__ = ["build_registry"]
