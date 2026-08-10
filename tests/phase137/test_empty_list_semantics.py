"""E-CRIT1 — empty allowed_agent_profiles = DENY, parity across BOTH surfaces.

The canonical deny already lives in
``core/registry/capability_registry.py::is_capability_in_scope`` (returns False on an
empty ``allowed_agent_profiles``). The advertising surface
``core/registry/index.py::get_index_for_profile`` still ALLOW-ALLs on empty aap today
(D-01, the bug). This test asserts PARITY: after the D-01 fix a tool with empty aap is
denied by BOTH surfaces.

RED at develop HEAD for the right reason: ``is_capability_in_scope`` already returns
False (green side), but ``get_index_for_profile`` still advertises empty-aap tools
(e.g. ``response``) to every profile — so the "not advertised" half FAILS until 137-06
flips index.py. Assertions route through the real registry hops only.

Analog: tests/phase135/test_scope_from_registry.py:63-77 (listed->True / unlisted->False).
"""
from __future__ import annotations

from fingpt_core.contracts.capability_registry import CapabilityStatus

# An arbitrary probe profile. Empty-aap means NO profile is listed, so the deny verdict
# is invariant to which profile probes it — any real profile id works.
PROBE_PROFILE = "agent_zero"


def _empty_aap_real_tool_ids(reg) -> list[str]:
    """REAL, non-deprecated tool ids whose allowed_agent_profiles is empty.

    These are exactly the entries that WOULD surface in get_index_for_profile under the
    HEAD allow-all default and must vanish under D-01 (fail-closed).
    """
    ids: list[str] = []
    for entry in reg.snapshot.entries:
        if entry.status != CapabilityStatus.REAL or entry.deprecated:
            continue
        if not entry.allowed_agent_profiles:
            ids.append(entry.id)
    return ids


def test_response_has_empty_aap(reg):
    """Anchor the fixture: ``response`` is the #1 empty-aap regression risk (Pitfall 1)."""
    entry = reg._by_id.get("response")
    assert entry is not None, "response tool must be registered"
    assert not entry.allowed_agent_profiles, (
        "response is expected to have EMPTY allowed_agent_profiles at HEAD "
        "(rides the allow-all default until D-02 grants + D-01 flip)"
    )


def test_is_capability_in_scope_denies_empty_aap(reg):
    """Canonical deny side (already correct): empty aap -> is_capability_in_scope False."""
    for tool_id in _empty_aap_real_tool_ids(reg):
        assert reg.is_capability_in_scope(profile=PROBE_PROFILE, capability_id=tool_id) is False, (
            f"{tool_id!r}: empty allowed_agent_profiles must be OUT of scope "
            f"(capability_registry canonical deny)"
        )


def test_index_denies_empty_aap_parity(reg):
    """Advertising side (D-01 target): empty aap must NOT be advertised by index.py.

    RED at HEAD — index.py still ALLOW-ALLs empty-aap tools, so every empty-aap REAL
    tool appears in the profile index and this parity assertion fails.
    """
    advertised_ids = {e["id"] for e in reg.get_index_for_profile(PROBE_PROFILE)}
    leaked = sorted(set(_empty_aap_real_tool_ids(reg)) & advertised_ids)
    assert not leaked, (
        "empty allowed_agent_profiles must be DENIED on the advertising surface too "
        f"(D-01 parity with is_capability_in_scope); index.py still allow-alls: {leaked}"
    )
