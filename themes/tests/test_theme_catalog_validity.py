"""Phase 94-05 — Theme catalog validity contract.

Every YAML under VM107/themes/catalog/ (excluding ``_schema.yaml``) must:
* parse as YAML,
* carry the required top-level keys per ``_schema.yaml``,
* have well-formed evidence_rules (weight >= 1, exactly one trigger key),
* declare emerging/strengthening/dominant thresholds + hysteresis_band.

Wave 3a ships ~14 themes per CONTEXT.md §H; future PRs extend the catalog
to 30-40. This test is the bare contract — adding a new theme means adding
a YAML that satisfies the schema, no engine code changes required.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import yaml


CATALOG_DIR = Path(__file__).resolve().parents[1] / "catalog"

REQUIRED_KEYS = {
    "theme_id",
    "title",
    "category",
    "description",
    "countries",
    "supporting_indicators",
    "affected_assets",
    "evidence_rules",
    "state_thresholds",
}

ALLOWED_CATEGORIES = {
    "inflation",
    "growth",
    "liquidity",
    "policy",
    "fx",
    "commodities",
    "tech",
    "geopolitics",
}

ALLOWED_EVENT_TYPES = {
    "macro_release",
    "central_bank",
    "regime_change",
    "research",
    "forecast_update",
    "discovery",
}

TRIGGER_KEYS = {"indicator", "event_type", "forecast"}


def _catalog_yamls() -> list[Path]:
    return sorted(p for p in CATALOG_DIR.glob("*.yaml") if p.name != "_schema.yaml")


def test_all_themes_load_at_least_fourteen():
    yamls = _catalog_yamls()
    assert len(yamls) >= 14, (
        f"CONTEXT.md §H expects ~14 baseline themes; found {len(yamls)} in {CATALOG_DIR}"
    )
    for path in yamls:
        with path.open() as f:
            spec = yaml.safe_load(f)
        assert isinstance(spec, dict), f"{path.name} must parse to a dict"
        missing = REQUIRED_KEYS - set(spec.keys())
        assert not missing, f"{path.name} missing required keys: {sorted(missing)}"


def test_theme_id_matches_filename_stem():
    for path in _catalog_yamls():
        with path.open() as f:
            spec = yaml.safe_load(f)
        assert spec["theme_id"] == path.stem, (
            f"{path.name}: theme_id {spec['theme_id']!r} must equal filename stem {path.stem!r}"
        )


def test_categories_are_allowed():
    for path in _catalog_yamls():
        with path.open() as f:
            spec = yaml.safe_load(f)
        assert spec["category"] in ALLOWED_CATEGORIES, (
            f"{path.name}: category {spec['category']!r} not in {sorted(ALLOWED_CATEGORIES)}"
        )


def test_evidence_rules_well_formed():
    for path in _catalog_yamls():
        with path.open() as f:
            spec = yaml.safe_load(f)
        rules = spec["evidence_rules"]
        assert isinstance(rules, list) and len(rules) >= 1, (
            f"{path.name}: evidence_rules must be non-empty list"
        )
        for i, rule in enumerate(rules):
            assert isinstance(rule, dict), f"{path.name} rule[{i}] must be dict"
            assert "weight" in rule, f"{path.name} rule[{i}] missing weight"
            assert isinstance(rule["weight"], int) and rule["weight"] >= 1, (
                f"{path.name} rule[{i}] weight must be int >= 1"
            )
            triggers_present = TRIGGER_KEYS.intersection(rule.keys())
            assert len(triggers_present) == 1, (
                f"{path.name} rule[{i}] must have exactly one of {sorted(TRIGGER_KEYS)}; "
                f"got {sorted(triggers_present)}"
            )
            if "event_type" in rule:
                assert rule["event_type"] in ALLOWED_EVENT_TYPES, (
                    f"{path.name} rule[{i}] event_type {rule['event_type']!r} not in "
                    f"{sorted(ALLOWED_EVENT_TYPES)}"
                )


def test_state_thresholds_present_and_ordered():
    for path in _catalog_yamls():
        with path.open() as f:
            spec = yaml.safe_load(f)
        st = spec["state_thresholds"]
        for key in (
            "emerging_min_strength",
            "strengthening_min_strength",
            "dominant_min_strength",
            "hysteresis_band",
        ):
            assert key in st, f"{path.name}: state_thresholds missing {key}"
            assert isinstance(st[key], int), f"{path.name}: {key} must be int"
        assert 0 <= st["emerging_min_strength"] < st["strengthening_min_strength"] < st[
            "dominant_min_strength"
        ] <= 100, (
            f"{path.name}: thresholds must be 0 <= emerging < strengthening < dominant <= 100"
        )
        assert 0 <= st["hysteresis_band"] <= 20, (
            f"{path.name}: hysteresis_band must be in [0, 20] (5 typical)"
        )
