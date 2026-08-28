"""Phase 169 Plan 02 Task 1 — DomainDefinition loader unit tests.

Proves the typed `DomainDefinition` model (D-11):
- `from_profile(...)` parses a `domain_definition:` block via `yaml.safe_load` ONLY,
- exposes `reasoning_rules` + `version` (surfaced as `domain_definition_version`),
- the deterministic `current_state` classifier over `reasoning_rules` thresholds,
- rejects a block missing a required key with a clear validation error.

This is the schema Plan 169-04 authors the 12 real profile blocks against — the
contract is pinned here now (fixture-based, no on-disk profile edits).
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.agents.domain_definition import DomainDefinition


_VALID_BLOCK = {
    "version": "1.0.0",
    "knowledge_version": "kb-2026.08",
    "indicators": ["CPIAUCSL", "PCEPI", "ISM_PRICES"],
    "signal_roles": {"lead": ["ISM_PRICES"], "lag": ["CPIAUCSL"]},
    "horizons": ["NOWCAST", "NEAR_TERM"],
    "calendar": "monthly-cpi",
    "materiality_thresholds": {"level": 0.5, "momentum": 0.3},
    "evaluation": {"correctness_kpi": "engine-lock respected = 1.0"},
    "ontology_path": "macro/inflation/ontology.md",
    "knowledge_path": "macro/inflation/knowledge.md",
    "reasoning_rules": {
        "default_state": "INDETERMINATE",
        "state_rules": [
            {"state": "DISINFLATION", "momentum_max": -0.1},
            {"state": "STICKY_SERVICES", "level_min": 0.3, "momentum_min": -0.1},
        ],
        "claim_templates": [
            {
                "claim_class": "OBSERVATION",
                "subject": "{domain} in {geography}",
                "predicate": "is currently classified as",
                "object": "{state}",
                "horizon": "NOWCAST",
                "invalidation_conditions": ["level crosses 0"],
                "assumptions": ["state read is fresh"],
            }
        ],
        "invalidation_conditions": ["next release reverses momentum sign"],
    },
}


def _profile_yaml() -> str:
    return textwrap.dedent(
        """
        id: vm107.inflation_domain_analyst
        phase: 95
        domain_definition:
          version: "2.1.0"
          knowledge_version: "kb-2026.08"
          indicators: [CPIAUCSL, PCEPI]
          signal_roles:
            lead: [ISM_PRICES]
            lag: [CPIAUCSL]
          horizons: [NOWCAST]
          calendar: monthly-cpi
          materiality_thresholds:
            level: 0.5
          evaluation:
            correctness_kpi: "engine-lock respected = 1.0"
          reasoning_rules:
            default_state: INDETERMINATE
            state_rules:
              - state: DISINFLATION
                momentum_max: -0.1
            claim_templates:
              - claim_class: OBSERVATION
                subject: "{domain}"
                predicate: "is"
                object: "{state}"
                horizon: NOWCAST
            invalidation_conditions: ["momentum flips"]
        """
    )


def test_from_profile_dict_block_parses_and_exposes_fields():
    dd = DomainDefinition.from_profile(dict(_VALID_BLOCK))
    assert dd.version == "1.0.0"
    assert dd.domain_definition_version == "1.0.0"
    assert dd.knowledge_version == "kb-2026.08"
    assert "CPIAUCSL" in dd.indicators
    assert dd.signal_roles.lead == ("ISM_PRICES",)
    assert dd.reasoning_rules.default_state == "INDETERMINATE"
    assert len(dd.reasoning_rules.claim_templates) == 1


def test_from_profile_extracts_top_level_block_from_full_profile(tmp_path: Path):
    path = tmp_path / "vm107.inflation_domain_analyst.yaml"
    path.write_text(_profile_yaml())
    dd = DomainDefinition.from_profile(path)
    assert dd.version == "2.1.0"
    assert dd.reasoning_rules.claim_templates[0].claim_class == "OBSERVATION"


def test_from_profile_raises_on_missing_required_key():
    bad = dict(_VALID_BLOCK)
    del bad["reasoning_rules"]
    with pytest.raises(ValidationError):
        DomainDefinition.from_profile(bad)


def test_from_profile_raises_when_block_absent(tmp_path: Path):
    path = tmp_path / "no_block.yaml"
    path.write_text("id: vm107.inflation_domain_analyst\nphase: 95\n")
    with pytest.raises((KeyError, ValueError)):
        DomainDefinition.from_profile(path)


def test_classifier_is_deterministic_over_thresholds():
    dd = DomainDefinition.from_profile(dict(_VALID_BLOCK))
    # momentum below -0.1 -> DISINFLATION (first matching rule wins)
    assert dd.reasoning_rules.classify(level=0.4, momentum=-0.3, surprise=None) == "DISINFLATION"
    # level>=0.3 and momentum>=-0.1 -> STICKY_SERVICES
    assert dd.reasoning_rules.classify(level=0.4, momentum=0.0, surprise=None) == "STICKY_SERVICES"
    # nothing matches -> default
    assert dd.reasoning_rules.classify(level=0.0, momentum=0.0, surprise=None) == "INDETERMINATE"
    # None level cannot satisfy a level-bounded rule
    assert dd.reasoning_rules.classify(level=None, momentum=0.0, surprise=None) == "INDETERMINATE"


def test_from_profile_rejects_non_mapping():
    with pytest.raises((TypeError, ValueError)):
        DomainDefinition.from_profile(12345)  # type: ignore[arg-type]
