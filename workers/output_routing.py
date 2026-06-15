"""Phase 85.1 output routing: maps agent profile_id → persistence helper.

Routes the raw JSON output from each Agent Zero profile to the correct
persistence module so there is no cross-contamination between tables.

Pattern 5 routing table (from 85.1-RESEARCH.md):
    vm107.macro_release_analyst        → economic_event_analysis.insert_analysis
    vm107.macro_asset_exposure_analyst → economic_event_asset_exposure.batch_insert
    vm107.macro_executive_summary_writer → economic_event_summary.write_summary  (or update_summary)
    vm107.macro_indicator_describer    → economic_indicator_description.upsert_description

WHY late imports for persistence modules:
    Each persistence helper imports psycopg2 + connection factory which requires
    POSTGRES_* env vars. Importing at module top forces the dispatcher to require
    a live Postgres at startup — even for unit tests. Late imports (inside
    ``parse_and_persist``) allow test monkeypatches to fire before any real DB
    connection is attempted.

WHY attribute-access (``module.fn``) not ``from module import fn``:
    pytest's ``monkeypatch.setattr`` / ``unittest.mock.patch`` replaces the
    attribute on the module object. If we use ``from module import fn`` and then
    call the local name ``fn``, the patch is invisible (we hold a reference to
    the original function object, not the module attribute). Accessing via
    ``module.fn(...)`` at call time means we always pick up the patched version.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class OutputParseError(ValueError):
    """Raised when agent output cannot be parsed as JSON."""


class UnknownProfileError(KeyError):
    """Raised when profile_id is not in the routing table."""


# ---------------------------------------------------------------------------
# JSON parse helper
# ---------------------------------------------------------------------------

def parse_agent_json(raw: str) -> dict:
    """Parse agent output to a dict; strips markdown code fences if present.

    Agent Zero often wraps JSON in ```json ... ``` markdown fences. This
    helper strips them before parsing.

    Args:
        raw: Raw agent output string.

    Returns:
        Parsed dict.

    Raises:
        OutputParseError: If the string cannot be parsed as JSON after stripping.
    """
    text = raw.strip()
    # Strip markdown code fence: ```json ... ``` or ``` ... ```
    if text.startswith("```"):
        lines = text.splitlines()
        # Remove opening fence (```json or ```)
        lines = lines[1:]
        # Remove closing fence if present
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        raise OutputParseError(
            f"Failed to parse agent output as JSON: {exc!r}\nRaw (first 200 chars): {raw[:200]!r}"
        ) from exc


# ---------------------------------------------------------------------------
# Main routing function
# ---------------------------------------------------------------------------

def parse_and_persist(
    profile_id: str,
    raw: str,
    telemetry: dict,
    goal_payload: dict,
) -> str:
    """Parse agent output and persist to the correct table for the given profile.

    Args:
        profile_id: Agent profile identifier (e.g. "vm107.macro_release_analyst").
        raw: Raw agent output string (JSON, possibly wrapped in markdown fences).
        telemetry: Telemetry dict from _dispatch_agent_sync (includes b1_artifact_id).
        goal_payload: Goal payload dict with at minimum "event_id" and "indicator_id".

    Returns:
        envelope_id (str): Either from telemetry["b1_artifact_id"] or a freshly
        generated UUID.

    Raises:
        UnknownProfileError: If profile_id is not in the routing table.
        OutputParseError: If raw cannot be parsed as JSON.
    """
    envelope_id: str = telemetry.get("b1_artifact_id") or str(uuid.uuid4())
    event_id: str = goal_payload.get("event_id", "")
    indicator_id: str = goal_payload.get("indicator_id", "")

    parsed = parse_agent_json(raw)

    if profile_id == "vm107.macro_release_analyst":
        # Late import: avoid requiring Postgres at module load time (unit test safety)
        import persistence.economic_event_analysis as _ea
        _ea.insert_analysis(
            event_id=event_id,
            indicator_id=indicator_id,
            analysis=parsed,
            envelope_id=envelope_id,
        )
        return envelope_id

    if profile_id == "vm107.macro_asset_exposure_analyst":
        import persistence.economic_event_asset_exposure as _eea
        exposures = parsed.get("exposures", parsed)
        _eea.batch_insert(
            event_id=event_id,
            rows=exposures if isinstance(exposures, list) else [exposures],
            envelope_id=envelope_id,
        )
        return envelope_id

    if profile_id == "vm107.macro_executive_summary_writer":
        import persistence.economic_event_executive_summary as _ees
        summary_text = parsed.get("summary", parsed.get("executive_summary", str(parsed)))
        _ees.update_summary(
            event_id=event_id,
            ai_executive_summary_text=summary_text,
        )
        return envelope_id

    if profile_id == "vm107.macro_indicator_describer":
        import persistence.economic_indicator_description as _eid
        _eid.upsert_description(
            indicator_code=indicator_id,
            description_dict=parsed,
            model_version=telemetry.get("model_used", "unknown"),
            prompt_version="1.0.0",
        )
        return envelope_id

    raise UnknownProfileError(
        f"No persistence route registered for profile_id={profile_id!r}. "
        f"Known profiles: vm107.macro_release_analyst, vm107.macro_asset_exposure_analyst, "
        f"vm107.macro_executive_summary_writer, vm107.macro_indicator_describer"
    )


# ---------------------------------------------------------------------------
# Route table (for inspection / Plan 05 introspection)
# ---------------------------------------------------------------------------

PROFILE_TO_PERSISTENCE: dict[str, str] = {
    "vm107.macro_release_analyst": "persistence.economic_event_analysis.insert_analysis",
    "vm107.macro_asset_exposure_analyst": "persistence.economic_event_asset_exposure.batch_insert",
    "vm107.macro_executive_summary_writer": "persistence.economic_event_executive_summary.update_summary",
    "vm107.macro_indicator_describer": "persistence.economic_indicator_description.upsert_description",
}
