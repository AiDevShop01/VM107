"""Brain Part 2 §B9 lock — LLM-direct propose() rejected at API level.

Phase 87 Wave 5 — Task 1. Only deterministic Python proposers may write to
BeliefStore. Any proposer_id containing 'llm' or not in the allowlist raises
PermissionError before any DB writes.
"""
from __future__ import annotations


DETERMINISTIC_PROPOSERS: set[str] = {
    "macro_regime_analyst",
    # Future Phase 87 sibling decimal phases may add proposers
}


def authorize_proposer(proposer_id: str) -> None:
    """Raises PermissionError unless proposer_id ends in an allowlisted bare id
    and does not contain 'llm' anywhere in the string.
    """
    norm = proposer_id.lower()
    if "llm" in norm:
        raise PermissionError(
            f"LLM-direct propose blocked: {proposer_id}. "
            "Only deterministic proposers may call BeliefStore.propose()."
        )
    bare = proposer_id.split(".")[-1]
    if bare not in DETERMINISTIC_PROPOSERS:
        raise PermissionError(f"unknown proposer: {proposer_id}")
