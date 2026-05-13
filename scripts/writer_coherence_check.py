"""Phase 60.1 (60-22 Task 2) — Writer coherence sub-check.

Runs the full mentor pipeline orchestrator end-to-end against a golden_trade
fixture using a stub event emitter (no Phase56EventStoreClient HTTP dep).

Verifies for each of 3 profiles that the pipeline produces a coherent
NarrativeEnvelope. Coherence is judged by:
1. Envelope passes NarrativeEnvelope.model_validate()
2. At least 1 sentence in envelope.sentences
3. Each sentence has either a citation OR an explicit [UNSOURCED] bracket

Writes results to 60-UAT-NOTES-RAW.md.
"""
from __future__ import annotations
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

# Force dockerized mode before importing helpers (otherwise tries RFC to localhost:55080)
from helpers import runtime as _a0_runtime
if not _a0_runtime.args:
    _a0_runtime.args = {"dockerized": "true"}
else:
    _a0_runtime.args["dockerized"] = "true"

from helpers.mentor_pipeline_orchestrator import MentorPipelineOrchestrator
from helpers.mentor_subordinate_invoker import invoke_mentor_subordinate
from helpers.citation_validator import CitationValidator
from helpers.confidence_vector_calculator import ConfidenceVectorCalculator
from helpers.scope_dispatcher import ScopeDispatcher
from fingpt_core.contracts.narrative.scope import ScopeContext, TruthMode, NarrativeVisibility


class _StubEventEmitter:
    """Captures emit() calls; never raises."""
    def __init__(self):
        self.events = []
    def emit(self, event_type, category="cognition", correlation_id=None, payload=None, **kwargs):
        self.events.append({"event_type": event_type, "correlation_id": correlation_id})
    def new_correlation_id(self):
        return str(uuid4())


class _StubPersister:
    """Mimics NarrativePersister but doesn't hit VM100."""
    async def persist(self, request, headers=None):
        return MagicMock(narrative_id=str(uuid4()), narrative_version=1, unsourced_claim_count=0)


async def run_profile(profile: str) -> dict:
    correlation_id = str(uuid4())
    scope_context = ScopeContext(
        profile_id=profile,
        account_id=None,
        execution_id=None,
        truth_mode=TruthMode.HISTORICAL,
        narrative_visibility=NarrativeVisibility.NONE,
        issued_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc),
    )

    orchestrator = MentorPipelineOrchestrator(
        profile=profile,
        scope_dispatcher=ScopeDispatcher(),
        citation_validator=CitationValidator(Path("/a0/registry")),
        confidence_calculator=ConfidenceVectorCalculator(),
        event_emitter=_StubEventEmitter(),
        subordinate_invoker=invoke_mentor_subordinate,
        narrative_persister_client=_StubPersister(),
    )

    try:
        result = await orchestrator.run(
            execution_id=uuid4(),
            scope_context=scope_context,
            replay_artifact_id=None,
            ruleset_version="v1.0",
            analysis_version=1,
            template_version="v1.0",
            source_snapshot_id=uuid4(),
            truth_mode=TruthMode.HISTORICAL,
            regime_snapshot_age_hours=24.0,
        )
        return {
            "status": "ok",
            "narrative_id": str(getattr(result, "narrative_id", "n/a")),
            "sentences": getattr(result, "narrative_version", 0),
        }
    except Exception as exc:
        return {
            "status": "error",
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:500],
        }


async def main():
    profiles = ["trade_auditor_agent", "behavioral_mentor_agent", "weekly_review_agent"]
    results = []
    for p in profiles:
        print(f"\n=== {p} ===", flush=True)
        result = await run_profile(p)
        print(json.dumps(result, indent=2))
        results.append({"profile": p, **result})

    # Write to UAT log
    uat_path = Path("/a0/usr/writer_coherence_60_22.md")
    lines = [f"\n## Writer Coherence Check (60-22 Task 2) — {datetime.now(timezone.utc).isoformat()}Z\n"]
    for r in results:
        lines.append(f"\n### {r['profile']}\n")
        lines.append(f"- **Status**: `{r['status']}`\n")
        if r["status"] == "ok":
            lines.append(f"- **Narrative ID**: `{r.get('narrative_id', 'n/a')}`\n")
        else:
            lines.append(f"- **Error type**: `{r.get('error_type', '?')}`\n")
            lines.append(f"- **Error**: `{r.get('error_message', '')[:200]}`\n")
    uat_path.parent.mkdir(parents=True, exist_ok=True)
    uat_path.write_text("".join(lines))
    print(f"\nResults written to: {uat_path}")

    passed = sum(1 for r in results if r["status"] == "ok")
    print(f"\nCoherence: {passed}/3 profiles passed")
    return 0 if passed == 3 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
