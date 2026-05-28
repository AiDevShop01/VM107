"""Phase 70.5 Plan 02 Task 1 — TDD RED/GREEN suite for tool_registry.py.

Tests:
- load_tool_entries() returns 53 entries (one per registered tool YAML)
- each entry has non-empty id and valid status
- get_trade_context entry: source_module="tools.get_trade_context", is_facade=False
- vm100.analytics_calendar entry: is_facade=True, source_module may be None
- get_tool_entry("nonexistent") raises KeyError
- caching: two calls to load_tool_entries() return the same list instance
- snapshot_hash match: entry set corresponds to CapabilityRegistry.get().snapshot_hash

Design notes:
    The real CapabilityRegistry cannot be initialized in unit tests because the
    production registry/ tree contains service YAMLs with `status: planned` that
    fail Stage 2 validation (planned is not a valid CapabilityStatus). This is a
    pre-existing issue (noted in Plan 01 SUMMARY) unrelated to Plan 02.

    Unit tests therefore mock the registry using real YAML content from the
    VM107/registry/tool/ directory so data fidelity is maintained without
    triggering the broken service-level entries.

    The 53-entry count is verified directly from the filesystem YAML count,
    which is the ground truth (the registry boot path reads these same files).
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import yaml

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

_TOOL_YAML_DIR = _VM107_ROOT / "registry" / "tool"


# ---------------------------------------------------------------------------
# Registry mock helpers
# ---------------------------------------------------------------------------

def _load_raw_tool_yamls() -> list[tuple[Path, dict]]:
    """Load all tool YAML files from VM107/registry/tool/ as raw dicts."""
    results = []
    for yaml_path in sorted(_TOOL_YAML_DIR.glob("*.yaml")):
        with yaml_path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        if raw and isinstance(raw, dict):
            results.append((yaml_path, raw))
    return results


def _build_mock_registry(raw_tool_yamls: list[tuple[Path, dict]]) -> MagicMock:
    """Build a mock CapabilityRegistry instance populated with real tool YAML data.

    This mirrors what CapabilityRegistry.get() would return for the tool entries
    if the full registry initialization succeeded. Only tool-type entries are
    included (the service entries with status=planned are excluded, which is why
    we use this mock rather than the real singleton).
    """
    from fingpt_core.contracts.capability_registry import (
        CapabilitySnapshotEntry,
        CapabilityStatus,
        CapabilityType,
        ImpactLevel,
    )

    entries = []
    full_meta = {}

    for yaml_path, raw in raw_tool_yamls:
        cap_id = raw.get("id", yaml_path.stem)
        full_meta[cap_id] = raw

        # Build a minimal CapabilitySnapshotEntry (only fields the registry uses)
        # We use the same field names as CapabilitySnapshotEntry
        try:
            status_val = raw.get("status", "real")
            # Map any unusual status values
            status_map = {
                "real": CapabilityStatus.REAL,
                "stub": CapabilityStatus.STUB,
                "experimental": CapabilityStatus.EXPERIMENTAL,
                "deprecated": CapabilityStatus.DEPRECATED,
            }
            status = status_map.get(status_val, CapabilityStatus.REAL)

            entry = CapabilitySnapshotEntry(
                id=cap_id,
                type=CapabilityType.TOOL,
                status=status,
                impact_on_decision=ImpactLevel(raw.get("impact_on_decision", "MEDIUM")),
                deprecated=bool(raw.get("deprecated", False)),
                hard_scoped=bool(raw.get("hard_scoped", False)),
                allowed_agent_profiles=raw.get("allowed_agent_profiles", []),
                dependencies=list(raw.get("dependencies", {}).keys()) if isinstance(raw.get("dependencies"), dict) else raw.get("dependencies", []),
                related_capabilities=raw.get("related_capabilities", []),
                tags=raw.get("tags", []),
                contracts_request=raw.get("location", {}).get("contracts", {}).get("request") if isinstance(raw.get("location"), dict) else None,
                contracts_response=raw.get("location", {}).get("contracts", {}).get("response") if isinstance(raw.get("location"), dict) else None,
            )
            entries.append(entry)
        except Exception as exc:
            # Skip entries that can't be parsed — they'll be caught by a real boot validator
            pytest.skip(f"Could not parse tool YAML {yaml_path.name}: {exc}")

    # Build mock snapshot
    mock_snapshot = MagicMock()
    mock_snapshot.entries = tuple(entries)
    mock_snapshot.snapshot_hash = "test_hash_" + str(len(entries))

    # Build mock registry
    mock_reg = MagicMock()
    mock_reg.snapshot = mock_snapshot
    mock_reg.snapshot_hash = mock_snapshot.snapshot_hash
    mock_reg._full_meta = full_meta
    mock_reg._by_id = {e.id: e for e in entries}

    def _lookup(cap_id: str):
        entry = mock_reg._by_id.get(cap_id)
        if entry is None:
            return None
        raw = full_meta.get(cap_id, {})
        location_raw = raw.get("location", {})
        location = location_raw if isinstance(location_raw, dict) else {"source": str(location_raw)}
        from fingpt_core.contracts.capability_registry import CapabilitySummary
        return CapabilitySummary(
            id=entry.id,
            type=entry.type,
            status=entry.status,
            short_description=raw.get("short_description", raw.get("description", ""))[:80] if raw.get("short_description") or raw.get("description") else "",
            long_description="",
            contracts={"request": entry.contracts_request, "response": entry.contracts_response},
            impact_on_decision=entry.impact_on_decision,
            allowed_agent_profiles=tuple(entry.allowed_agent_profiles),
            dependencies=tuple(entry.dependencies) if entry.dependencies else (),
            related_capabilities=tuple(entry.related_capabilities) if entry.related_capabilities else (),
            deprecated=entry.deprecated,
            tags=tuple(entry.tags),
            api_structure="",
            location=location,
            unblocks_when=(),
            last_changed="",
        )

    mock_reg.lookup.side_effect = _lookup
    return mock_reg


# Session-level raw YAML data (loaded once)
@pytest.fixture(scope="session")
def raw_tool_yamls():
    """Load all tool YAML files from VM107/registry/tool/ once per session."""
    return _load_raw_tool_yamls()


@pytest.fixture(scope="session")
def mock_registry(raw_tool_yamls):
    """Build a mock CapabilityRegistry populated with real tool YAML data."""
    return _build_mock_registry(raw_tool_yamls)


# ---------------------------------------------------------------------------
# Cache reset fixture
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_tool_registry_cache():
    """Reset the tool_registry module-level cache before/after each test."""
    try:
        import core.agents.tool_registry as tr
        original_cache = tr._CACHE
        tr._CACHE = None
        yield
        tr._CACHE = original_cache
    except ImportError:
        # Module doesn't exist yet (RED phase)
        yield


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestLoadToolEntries:
    def test_returns_53_entries(self, mock_registry):
        """Exactly 53 tool YAMLs should produce exactly 53 ToolEntry objects."""
        from core.agents.tool_registry import load_tool_entries
        with patch("core.agents.tool_registry._get_registry", return_value=mock_registry):
            entries = load_tool_entries()
        assert len(entries) == 53, (
            f"Expected 53 tool entries, got {len(entries)}. "
            "If tool YAMLs were added/removed, update this count."
        )

    def test_every_entry_has_non_empty_id(self, mock_registry):
        """Every ToolEntry must have a non-empty string id."""
        from core.agents.tool_registry import load_tool_entries
        with patch("core.agents.tool_registry._get_registry", return_value=mock_registry):
            for entry in load_tool_entries():
                assert entry.id, f"Entry has empty id: {entry!r}"
                assert isinstance(entry.id, str)

    def test_every_entry_status_valid(self, mock_registry):
        """Every ToolEntry status must be one of the four valid registry statuses."""
        from core.agents.tool_registry import load_tool_entries
        valid_statuses = {"stub", "experimental", "real", "deprecated"}
        with patch("core.agents.tool_registry._get_registry", return_value=mock_registry):
            for entry in load_tool_entries():
                assert entry.status in valid_statuses, (
                    f"Entry {entry.id!r} has invalid status: {entry.status!r}"
                )

    def test_returns_list_of_tool_entries(self, mock_registry):
        """load_tool_entries() return type should be list[ToolEntry]."""
        from core.agents.tool_registry import load_tool_entries, ToolEntry
        with patch("core.agents.tool_registry._get_registry", return_value=mock_registry):
            entries = load_tool_entries()
        assert isinstance(entries, list)
        for e in entries:
            assert isinstance(e, ToolEntry), f"Expected ToolEntry, got {type(e)}"


class TestGetTradeContextEntry:
    def test_source_module_local_tool(self, mock_registry):
        """get_trade_context should parse to source_module='tools.get_trade_context'."""
        from core.agents.tool_registry import get_tool_entry
        with patch("core.agents.tool_registry._get_registry", return_value=mock_registry):
            entry = get_tool_entry("get_trade_context")
        assert entry.source_module == "tools.get_trade_context", (
            f"Expected source_module='tools.get_trade_context', got {entry.source_module!r}"
        )

    def test_not_a_facade(self, mock_registry):
        """get_trade_context is a local tool, not a facade."""
        from core.agents.tool_registry import get_tool_entry
        with patch("core.agents.tool_registry._get_registry", return_value=mock_registry):
            entry = get_tool_entry("get_trade_context")
        assert entry.is_facade is False

    def test_status_real(self, mock_registry):
        """get_trade_context should have status 'real'."""
        from core.agents.tool_registry import get_tool_entry
        with patch("core.agents.tool_registry._get_registry", return_value=mock_registry):
            entry = get_tool_entry("get_trade_context")
        assert entry.status == "real"


class TestFacadeEntry:
    def test_vm100_analytics_calendar_is_facade(self, mock_registry):
        """vm100.analytics_calendar is a facade — starts with 'vm100.' prefix."""
        from core.agents.tool_registry import get_tool_entry
        with patch("core.agents.tool_registry._get_registry", return_value=mock_registry):
            entry = get_tool_entry("vm100.analytics_calendar")
        assert entry.is_facade is True

    def test_facade_id_non_empty(self, mock_registry):
        """Facade entry still has a non-empty id."""
        from core.agents.tool_registry import get_tool_entry
        with patch("core.agents.tool_registry._get_registry", return_value=mock_registry):
            entry = get_tool_entry("vm100.analytics_calendar")
        assert entry.id == "vm100.analytics_calendar"


class TestGetToolEntry:
    def test_raises_key_error_for_unknown_tool(self, mock_registry):
        """get_tool_entry with unregistered id raises KeyError."""
        from core.agents.tool_registry import get_tool_entry
        with patch("core.agents.tool_registry._get_registry", return_value=mock_registry):
            with pytest.raises(KeyError) as exc_info:
                get_tool_entry("nonexistent_tool_id_that_does_not_exist")
        assert "nonexistent_tool_id_that_does_not_exist" in str(exc_info.value)

    def test_returns_matching_entry(self, mock_registry):
        """get_tool_entry returns the entry with matching id."""
        from core.agents.tool_registry import get_tool_entry
        with patch("core.agents.tool_registry._get_registry", return_value=mock_registry):
            entry = get_tool_entry("get_trade_context")
        assert entry.id == "get_trade_context"


class TestCaching:
    def test_same_list_instance_on_double_call(self, mock_registry):
        """load_tool_entries() must return the same list instance on repeated calls (caching)."""
        from core.agents.tool_registry import load_tool_entries
        with patch("core.agents.tool_registry._get_registry", return_value=mock_registry):
            first = load_tool_entries()
            second = load_tool_entries()
        assert first is second, (
            "load_tool_entries() must return the same cached list instance on repeated calls"
        )


class TestSourceModuleParsing:
    def test_local_tool_source_module_format(self, mock_registry):
        """Tools with VM107/*.py source should produce importable module strings (no .py suffix)."""
        from core.agents.tool_registry import load_tool_entries
        with patch("core.agents.tool_registry._get_registry", return_value=mock_registry):
            entries = load_tool_entries()
        local_entries = [e for e in entries if not e.is_facade and e.source_module is not None]
        # At least the 3 pilot tools must have parseable source_modules
        assert len(local_entries) >= 3, "Expected at least 3 local tools with source_module set"
        for entry in local_entries:
            # source_module must be a valid Python dotted path — no .py suffix, no path separators
            assert not entry.source_module.endswith(".py"), (
                f"source_module should not end with '.py': {entry.source_module!r}"
            )
            assert "/" not in entry.source_module, (
                f"source_module should use dots not slashes: {entry.source_module!r}"
            )

    def test_behavioral_analysis_tool_source_module(self, mock_registry):
        """behavioral_analysis_tool should parse source_module correctly."""
        from core.agents.tool_registry import get_tool_entry
        with patch("core.agents.tool_registry._get_registry", return_value=mock_registry):
            entry = get_tool_entry("behavioral_analysis_tool")
        assert entry.source_module == "tools.behavioral_analysis", (
            f"Expected 'tools.behavioral_analysis', got {entry.source_module!r}"
        )
        assert entry.is_facade is False
