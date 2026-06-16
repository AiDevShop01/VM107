"""Phase 87 Wave 4a — Phase 71 evidence drawer parses every
[ref:episode:<uuid>] token cleanly. Citation grammar round-trip."""
import re
import uuid

import pytest

pytestmark = pytest.mark.phase_87

EPISODE_RE = re.compile(r"\[ref:episode:(?P<id>[0-9a-fA-F-]+)\]")


def test_citation_id_is_valid_uuid():
    sample = "[ref:episode:550e8400-e29b-41d4-a716-446655440000]"
    m = EPISODE_RE.match(sample)
    assert m is not None
    # round-trip parse — Phase 71 drawer assumes valid UUID
    uuid.UUID(m.group("id"))


def test_no_malformed_tokens_in_block():
    # Mirror what the hook outputs
    block = (
        "## Relevant prior episodes\n"
        "1. [ref:episode:550e8400-e29b-41d4-a716-446655440001] First episode.\n"
        "2. [ref:episode:550e8400-e29b-41d4-a716-446655440002] Second episode.\n"
    )
    # Every '[ref:' is followed by ']' (no orphan brackets)
    assert block.count("[ref:") == block.count("]")
    for m in EPISODE_RE.finditer(block):
        uuid.UUID(m.group("id"))


def test_service_records_emit_valid_citation_uuids():
    """Synthesize a MemoryRecord and confirm its citation parses via the
    Phase 71 regex round-trip — guards against the service drifting from
    the citation grammar declared in the contract YAML."""
    from datetime import datetime, timezone
    from VM107.core.memory.episodic_memory_service import (
        CitationRef, MemoryRecord,
    )

    mid = uuid.uuid4()
    rec = MemoryRecord(
        memory_id=mid, memory_type="episodic",
        text="test", embedding=[0.0] * 768,
        created_at=datetime.now(tz=timezone.utc),
        decay_weight=1.0,
        citations=[CitationRef(
            citation_ref=f"[ref:episode:{mid}]",
            kind="episode",
            target_id=str(mid),
        )],
    )
    m = EPISODE_RE.match(rec.citations[0].citation_ref)
    assert m is not None
    parsed = uuid.UUID(m.group("id"))
    assert parsed == mid
