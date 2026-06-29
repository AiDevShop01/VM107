"""Phase 47.6 capability-registry lock — verify ``find_country_subgraph``
is declared in ``registry/tool/graph_search_tool.yaml``.

Phase 96 Plan 11 adds the ``find_country_subgraph`` template to the
existing ``GraphSearchTool`` (a parent tool registered under its own
YAML). Per the LD-7 governance pattern, sub-templates register via
amendment of the parent tool's YAML — there is no ``tool_template``
top-level capability type in the gsd-plan-checker parser's
VALID_TYPES frozenset.

This test asserts the amendment landed:

    1. The parent YAML ``registry/tool/graph_search_tool.yaml`` exists.
    2. It carries a ``templates:`` section.
    3. ``find_country_subgraph`` appears under it with ``phase: 96`` and
       the required ``request_params`` schema (iso_alpha2 + depth bounds 1..3).
    4. ``last_changed`` is at least the Phase 96 amendment date.
"""
from __future__ import annotations

import datetime as _dt
import pathlib

import pytest
import yaml

REGISTRY_ROOT = pathlib.Path(__file__).resolve().parents[1]
YAML_PATH = REGISTRY_ROOT / "tool" / "graph_search_tool.yaml"

PHASE_96_AMENDMENT_DATE = "2026-06-29"


def _load_yaml() -> dict:
    assert YAML_PATH.exists(), (
        f"Phase 47.6 capability-registry lock — expected parent tool YAML at "
        f"{YAML_PATH} (Phase 96 Plan 11 amends this file to declare "
        f"find_country_subgraph)."
    )
    return yaml.safe_load(YAML_PATH.read_text())


def test_parent_tool_yaml_exists_and_parses():
    data = _load_yaml()
    assert data["id"] == "graph_search_tool"
    assert data["type"] == "tool"
    assert data["capability_type"] == "tool"
    assert data["vm"] == "vm107"


def test_templates_section_present():
    data = _load_yaml()
    assert "templates" in data, (
        "Phase 96 Plan 11 lock — graph_search_tool.yaml must declare a "
        "templates: section listing every sub-template."
    )
    assert isinstance(data["templates"], dict), (
        "templates: must be a mapping of template-name → template-schema."
    )


def test_find_country_subgraph_registered_under_templates():
    data = _load_yaml()
    templates = data.get("templates", {})
    assert "find_country_subgraph" in templates, (
        "Phase 96 Plan 11 lock — find_country_subgraph must be declared in "
        "graph_search_tool.yaml templates: section (Phase 47.6 capability-"
        "registry lock — sub-templates register via parent-YAML amendment, "
        "not via a standalone REGISTER_CAPABILITY directive)."
    )
    tmpl = templates["find_country_subgraph"]
    assert tmpl["phase"] == 96
    rp = tmpl["request_params"]
    assert rp["iso_alpha2"]["required"] is True
    assert rp["iso_alpha2"]["pattern"] == "^[A-Z]{2}$"
    assert rp["depth"]["minimum"] == 1
    assert rp["depth"]["maximum"] == 3
    assert rp["depth"]["default"] == 1
    bounds = tmpl.get("bounds", {})
    assert bounds.get("depth") == [1, 3]
    assert tmpl.get("added_in_phase") == 96


def test_response_shape_documented():
    data = _load_yaml()
    tmpl = data["templates"]["find_country_subgraph"]
    shape = tmpl.get("response_shape", {})
    assert shape.get("nodes") == "list"
    assert shape.get("edges") == "list"


def test_last_changed_bumped_to_phase_96_amendment():
    data = _load_yaml()
    last_changed = data.get("last_changed")
    assert last_changed is not None, "last_changed required"
    # YAML may parse this as a date or a string — normalise.
    if isinstance(last_changed, _dt.date):
        last_changed_str = last_changed.isoformat()
    else:
        last_changed_str = str(last_changed)
    assert last_changed_str >= PHASE_96_AMENDMENT_DATE, (
        f"last_changed must reflect the Phase 96 Plan 11 amendment date "
        f"({PHASE_96_AMENDMENT_DATE} or later); got {last_changed_str}."
    )


def test_pre_existing_templates_still_listed():
    """Amendment must preserve the 6 pre-Phase-96 templates declared on the tool."""
    data = _load_yaml()
    templates = data.get("templates", {})
    for name in (
        "find_predecessors",
        "find_successors",
        "find_related",
        "find_path",
        "find_methods_using",
        "find_validated_relationships",
    ):
        assert name in templates, (
            f"Pre-existing template '{name}' missing from amended YAML — "
            "Phase 96 Plan 11 must add find_country_subgraph WITHOUT removing "
            "any previously-declared template."
        )
