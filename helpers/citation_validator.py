"""Citation enforcement per CTX-§4 — deterministic Python guardrail between LLM writer output and persistence.

Three failure modes the validator catches:
  1. ASSERTION sentence with no [ref:...] citation
  2. ASSERTION sentence citing an unknown registry_id (not in VM107/registry/)
  3. META sentence containing any citation
  4. SUMMARY with assertion-shaped content but zero citations (conservative heuristic)

Validator raises CitationViolation on first failure. Orchestrator (60-06) catches and retries
writer up to 2x. After 2 retries: auto_bracket_unsourced() rewrites remaining uncited ASSERTIONs.

IMPORTANT: auto_bracket_unsourced() is ONLY called by the orchestrator after bounded retries
are exhausted. This module exposes both enforce() (hard-fail) and auto_bracket_unsourced()
(graceful degradation). The orchestrator picks which to call based on retry count.
The validator does NOT auto-bracket inside enforce() — that's the orchestrator's decision
per CONTEXT.md §4 Pitfall 7.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from fingpt_core.contracts.narrative.envelope import NarrativeEnvelope
from fingpt_core.contracts.narrative.sentence import NarrativeSentence, SentenceClass
from fingpt_core.contracts.narrative.citation import CitationToken

REGISTRY_SUBDIRS = [
    "tool",
    "behavioral_pattern",
    "replay_template",
    "event_type",
    "signal",
    "skill",
    "agent_profile",
    "service",
    "collection",
    "state_machine",
    "counterfactual_scenario",  # Phase 61-01 — Option B (dotted scenario_ids in field segment)
]

# Heuristic regex for assertion-shaped SUMMARY content (conservative).
# Matches strong claim verbs and numeric percentages.
ASSERTION_VERB_PATTERN = re.compile(
    r"\b(indicates?|shows?|reveals?|demonstrates?|implies|exhibits?|displays?|registers?)\b"
    r"|\b\d+\.?\d*\s*%",
    re.IGNORECASE,
)


class CitationViolation(Exception):
    """Raised when a narrative sentence violates CTX-§4 citation rules."""

    def __init__(self, sentence_index: int, sentence_class: str, reason: str) -> None:
        self.sentence_index = sentence_index
        self.sentence_class = sentence_class
        self.reason = reason
        super().__init__(
            f"sentence[{sentence_index}] class={sentence_class}: {reason}"
        )


def load_known_registry_ids(registry_root: Path) -> frozenset[str]:
    """Scan VM107/registry/{subdirs}/ for *.yaml files and extract 'id' fields.

    Returns a frozenset of all known registry IDs. If a subdirectory does not
    exist yet (e.g., skill/, agent_profile/ before Phase 60-07 creates them),
    it is silently skipped. Malformed YAML files are skipped with no error.
    """
    ids: set[str] = set()
    for subdir in REGISTRY_SUBDIRS:
        full_dir = registry_root / subdir
        if not full_dir.is_dir():
            continue
        for yaml_file in full_dir.glob("*.yaml"):
            try:
                data = yaml.safe_load(yaml_file.read_text())
                if isinstance(data, dict) and "id" in data:
                    ids.add(str(data["id"]))
            except Exception:
                # Malformed YAML — skip; registry YAML test (60-07) catches these.
                continue
    return frozenset(ids)


class CitationValidator:
    """Deterministic citation enforcement per CTX-§4.

    Usage:
        validator = CitationValidator(Path("/Volumes/ HardDrive/FinGPT/VM107/registry"))
        try:
            validator.enforce(envelope)
        except CitationViolation as exc:
            # retry writer or call auto_bracket_unsourced()
            ...
    """

    def __init__(self, registry_root: Path) -> None:
        """Load known registry IDs from all registry subdirectories."""
        self._known: frozenset[str] = load_known_registry_ids(registry_root)

    def enforce(self, envelope: NarrativeEnvelope) -> None:
        """Validate all sentences in the envelope. Raises CitationViolation on first failure.

        Rules:
          - ASSERTION: requires >= 1 citation; each citation registry_id must be known.
          - META:      must NOT have any citations.
          - SUMMARY:   if 0 citations AND assertion-shaped text → violation.
          - TRANSITION: citations optional; if present, registry_ids must be known.
        """
        for sentence in envelope.sentences:
            self._check_sentence(sentence)

    def _check_sentence(self, sentence: NarrativeSentence) -> None:
        cls = sentence.sentence_class
        cites = sentence.citations

        if cls == SentenceClass.META:
            if cites:
                raise CitationViolation(
                    sentence.sentence_index,
                    cls.value,
                    "META sentences cannot contain citations",
                )
            return

        if cls == SentenceClass.TRANSITION:
            # Citations are optional for TRANSITION; if present, IDs must be known.
            self._check_registry_ids(sentence, cites)
            return

        if cls == SentenceClass.ASSERTION:
            if not cites:
                raise CitationViolation(
                    sentence.sentence_index,
                    cls.value,
                    "ASSERTION requires at least one [ref:...] citation",
                )
            self._check_registry_ids(sentence, cites)
            return

        if cls == SentenceClass.SUMMARY:
            # Accept with citations (still validate IDs), but reject uncited
            # assertion-shaped text (conservative heuristic — if in doubt, accept).
            if not cites and ASSERTION_VERB_PATTERN.search(sentence.text):
                raise CitationViolation(
                    sentence.sentence_index,
                    cls.value,
                    "SUMMARY contains assertion-shaped content without citation",
                )
            self._check_registry_ids(sentence, cites)
            return

    def _check_registry_ids(
        self,
        sentence: NarrativeSentence,
        cites: list[CitationToken],
    ) -> None:
        for c in cites:
            if c.registry_id == "counterfactual":
                # Phase 61-01 Option B: [ref:counterfactual:<field>] citations.
                # Two supported forms:
                #   (a) [ref:counterfactual:cf_<uuid>] — artifact-level: no registry lookup needed.
                #   (b) [ref:counterfactual:<scenario_id>:<outcome_field>] — scenario-level:
                #       validate scenario_id against counterfactual_scenario registry.
                field = c.field
                if field.startswith("cf_"):
                    # Artifact-level citation — grammar-valid; no registry lookup.
                    continue
                # Scenario-level: extract scenario_id (first colon-separated segment).
                # field = "counterfactual.stop.atr_1_5:hypothetical_r"
                scenario_id = field.split(":")[0]
                if scenario_id not in self._known:
                    raise CitationViolation(
                        sentence.sentence_index,
                        sentence.sentence_class.value,
                        f"unknown counterfactual scenario_id in citation: {scenario_id!r}. "
                        f"Must be registered in VM107/registry/counterfactual_scenario/",
                    )
                continue
            if c.registry_id not in self._known:
                raise CitationViolation(
                    sentence.sentence_index,
                    sentence.sentence_class.value,
                    f"unknown registry_id: {c.registry_id}",
                )

    def auto_bracket_unsourced(self, envelope: NarrativeEnvelope) -> NarrativeEnvelope:
        """Return a NEW envelope with uncited ASSERTION sentences marked [UNSOURCED].

        Called by the orchestrator (60-06) ONLY after writer retries are exhausted.
        For each ASSERTION with 0 citations:
          - Prepends '[UNSOURCED] ' to the sentence text
          - Sets sentence.unsourced = True
        The envelope.unsourced_claim_count is incremented by the number of bracketed
        sentences.

        Frozen-class safe: uses model_copy(update=...) to produce new instances.
        """
        new_sentences: list[NarrativeSentence] = []
        unsourced_count = 0

        for s in envelope.sentences:
            if s.sentence_class == SentenceClass.ASSERTION and not s.citations:
                new_sentences.append(
                    s.model_copy(
                        update={
                            "text": f"[UNSOURCED] {s.text}",
                            "unsourced": True,
                        }
                    )
                )
                unsourced_count += 1
            else:
                new_sentences.append(s)

        return envelope.model_copy(
            update={
                "sentences": new_sentences,
                "unsourced_claim_count": envelope.unsourced_claim_count + unsourced_count,
            }
        )
