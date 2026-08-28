"""Phase 170 Plan 02 (SC#2 registry core) — CausalMechanismRegistry seed + lookup.

Proves the four load-bearing behaviors (170-02-PLAN <behavior>):
  1. build_registry() seeds one MechanismRecord per claim_template (with a
     subject/predicate) from every real vm107.*_domain_analyst.yaml block, and
     the inflation INTERPRETATION key resolves to a NON-EMPTY mechanism.
  2. A bare-correlation key ("gold_open_interest" -> "signals", INTERPRETATION)
     returns None — the deterministic REJECT signal (Constitution 11, SC#2).
  3. A malformed/absent domain_definition: block is skipped (never bricks).
  4. A leading-underscore scaffold domain file is skipped.

All inputs are real typed objects (Plan 01 fixtures + the real 169 blocks) — no
mocks. Deterministic + LLM-free (engine-lock D-02).
"""
from __future__ import annotations

import textwrap
from pathlib import Path

from core.causal.mechanism_registry import CausalMechanismRegistry, MechanismRecord
from core.causal.seed import build_registry


# ---------------------------------------------------------------------------
# 1. Seed emits records; the inflation INTERPRETATION key resolves to a mechanism
# ---------------------------------------------------------------------------


def test_seed_emits_records(seeded_registry: CausalMechanismRegistry) -> None:
    """The real 12 blocks seed a non-empty, frozen registry of MechanismRecords."""
    assert isinstance(seeded_registry, CausalMechanismRegistry)
    assert len(seeded_registry.records) > 0
    assert all(isinstance(r, MechanismRecord) for r in seeded_registry.records)


def test_seeded_hit_inflation_interpretation(
    seeded_registry: CausalMechanismRegistry, supported_assessment
) -> None:
    """The verified inflation INTERPRETATION key resolves to a non-empty mechanism."""
    claim = supported_assessment.claims[0]
    record = seeded_registry.lookup(
        supported_assessment.domain,
        claim.claim_class,
        claim.subject,
        claim.predicate,
    )
    assert record is not None, "seeded inflation INTERPRETATION key must resolve to a mechanism"
    assert record.mechanism.strip(), "registered mechanism must be non-empty (reuse-first)"
    assert record.domain == "inflation"


# ---------------------------------------------------------------------------
# 2. SC#2 core — a bare-correlation key has NO registered mechanism => None
# ---------------------------------------------------------------------------


def test_missing_mechanism_is_none_sc2(
    seeded_registry: CausalMechanismRegistry, bare_correlation_assessment
) -> None:
    """SC#2: 'gold_open_interest' -> 'signals' (INTERPRETATION) has no seeded
    mechanism => lookup returns None (the deterministic Causality REJECT signal,
    Constitution 11)."""
    claim = bare_correlation_assessment.claims[0]
    record = seeded_registry.lookup(
        bare_correlation_assessment.domain,
        claim.claim_class,
        claim.subject,
        claim.predicate,
    )
    assert record is None, "a bare-correlation key must have NO registered mechanism (SC#2)"


def test_none_key_component_never_matches(seeded_registry: CausalMechanismRegistry) -> None:
    """An unknown/None key component can never satisfy a lookup (Unknown != match)."""
    assert seeded_registry.lookup(None, "INTERPRETATION", "core services ex-shelter", "is the dominant driver of") is None
    assert seeded_registry.lookup("inflation", None, "core services ex-shelter", "is the dominant driver of") is None
    assert seeded_registry.lookup("inflation", "INTERPRETATION", None, "is the dominant driver of") is None
    assert seeded_registry.lookup("inflation", "INTERPRETATION", "core services ex-shelter", None) is None


# ---------------------------------------------------------------------------
# Determinism — registry_version is a reproducible content hash
# ---------------------------------------------------------------------------


def test_registry_version_deterministic(
    seeded_registry: CausalMechanismRegistry, real_profile_dir: Path
) -> None:
    """Rebuilding from the same profiles yields the same registry_version hash."""
    rebuilt = build_registry(real_profile_dir)
    assert rebuilt.registry_version == seeded_registry.registry_version
    assert len(seeded_registry.registry_version) == 64  # sha256 hexdigest


# ---------------------------------------------------------------------------
# 3 + 4. Malformed / non-mapping / underscore-scaffold blocks are skipped
# ---------------------------------------------------------------------------


def _valid_block(subject: str, predicate: str) -> str:
    return textwrap.dedent(
        f"""\
        id: vm107.testdomain_domain_analyst
        domain_definition:
          version: "1.0.0"
          knowledge_version: "test-v1"
          signal_roles:
            lead: [lead_signal_a]
            lag: [lag_signal_b]
          reasoning_rules:
            default_state: Neutral
            claim_templates:
              - claim_class: INTERPRETATION
                subject: "{subject}"
                predicate: "{predicate}"
                object: "the {{state}} reading"
                horizon: NEAR_TERM
                invalidation_conditions: ["signal_a momentum flips sign"]
                assumptions: ["structure holds"]
        """
    )


def test_malformed_and_scaffold_skipped(tmp_path: Path) -> None:
    """build_registry never raises on a malformed / non-mapping / underscore-
    scaffold profile — it skips them (fragile-tree floor) and still seeds the
    valid ones."""
    # A valid domain -> contributes exactly one record.
    (tmp_path / "vm107.testdomain_domain_analyst.yaml").write_text(
        _valid_block("test subject", "drives")
    )
    # Malformed block (missing required reasoning_rules) -> ValidationError, skipped.
    (tmp_path / "vm107.broken_domain_analyst.yaml").write_text(
        "domain_definition:\n  version: \"1.0.0\"\n"
    )
    # Non-mapping YAML -> safe_load returns a list, skipped.
    (tmp_path / "vm107.garbage_domain_analyst.yaml").write_text("- just\n- a\n- list\n")
    # Leading-underscore scaffold domain -> skipped even though it parses.
    (tmp_path / "vm107._scaffold_domain_analyst.yaml").write_text(
        _valid_block("SHOULD_NOT_LOAD", "signals")
    )

    registry = build_registry(tmp_path)  # must NOT raise

    subjects = {r.subject for r in registry.records}
    assert "test subject" in subjects, "the valid block must seed its record"
    assert "SHOULD_NOT_LOAD" not in subjects, "underscore-scaffold domain must be skipped"
    # Only the single valid template produced a record.
    assert len(registry.records) == 1
    assert registry.records[0].domain == "testdomain"


def test_empty_profile_dir_yields_empty_registry(tmp_path: Path) -> None:
    """No matching profiles => an empty (but valid, non-raising) registry."""
    registry = build_registry(tmp_path)
    assert isinstance(registry, CausalMechanismRegistry)
    assert registry.records == ()
