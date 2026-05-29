"""Phase 70.5 Decision 17 — structured-log envelope telemetry.

Single-line JSON emission per envelope. NO HTTP client. The log payload schema
IS the future VM106 ingestion schema — when VM106 ingest is ready, the swap is
"same JSON → HTTP POST" with zero envelope-side changes.

DESIGN INVARIANTS:
  - One JSON line per envelope emission.
  - Telemetry failure NEVER blocks tool execution (try/except).
  - Schema is frozen this phase — extending it requires a separate plan.

Public API:
    emit_envelope_log(envelope, ctx) -> None
    ENVELOPE_LOGGER_NAME            — "fingpt.envelope.tool"
    ENVELOPE_FALLBACK_LOGGER_NAME   — "fingpt.envelope.tool.fallback"
    ENVELOPE_LOG_EVENT_TYPE         — "tool_result_envelope_emitted"
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fingpt_core.contracts.invocation_context import InvocationContext
    from fingpt_core.contracts.tool_envelope import ToolResultEnvelope

ENVELOPE_LOGGER_NAME = "fingpt.envelope.tool"
ENVELOPE_FALLBACK_LOGGER_NAME = "fingpt.envelope.tool.fallback"
ENVELOPE_LOG_EVENT_TYPE = "tool_result_envelope_emitted"

_logger = logging.getLogger(ENVELOPE_LOGGER_NAME)
_fallback_logger = logging.getLogger(ENVELOPE_FALLBACK_LOGGER_NAME)


def _ensure_handler() -> None:
    """Attach a stderr StreamHandler if no handler is configured.

    Agent Zero's root logger defaults to WARNING with no handlers, so
    `_logger.info(...)` silently drops envelope JSON unless a handler is
    attached. This bootstrap runs once at module import — if the host
    application has its own logging config it can still override (handlers
    are additive; the host's handler wins ordering, but ours guarantees the
    line reaches stderr / docker logs at minimum).
    """
    if _logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(name)s %(message)s"))
    _logger.addHandler(handler)
    _logger.setLevel(logging.INFO)
    _logger.propagate = False
    if not _fallback_logger.handlers:
        fb_handler = logging.StreamHandler()
        fb_handler.setFormatter(logging.Formatter("%(name)s %(levelname)s %(message)s"))
        _fallback_logger.addHandler(fb_handler)
        _fallback_logger.setLevel(logging.WARNING)
        _fallback_logger.propagate = False


_ensure_handler()


def emit_envelope_log(
    envelope: "ToolResultEnvelope",
    ctx: "InvocationContext",
) -> None:
    """Emit Decision-17-shaped single-line JSON to ENVELOPE_LOGGER_NAME.

    Schema (matches Decision 17 verbatim, every key present even if null):
        event_type, envelope_id, parent_envelope_id, trace_id, agent_id,
        conversation_id, execution_depth, tool_id, tool_name, tool_version,
        outcome_class, success, confidence, freshness_seconds,
        registry_snapshot_hash, generated_at, len_failure_modes,
        len_normalization_warnings, len_citations.

    NEVER raises. Failure → WARNING on fallback logger; envelope continues.

    Args:
        envelope: The emitted ToolResultEnvelope (any T).
        ctx: The InvocationContext for this dispatch (carries trace_id, agent_id, etc.).
    """
    try:
        payload = {
            "event_type": ENVELOPE_LOG_EVENT_TYPE,
            "envelope_id": str(envelope.envelope_id),
            "parent_envelope_id": (
                str(envelope.parent_envelope_id)
                if envelope.parent_envelope_id is not None
                else None
            ),
            "trace_id": str(ctx.trace_id),
            "agent_id": ctx.agent_id,
            "conversation_id": ctx.conversation_id,
            "execution_depth": ctx.execution_depth,
            # tool_id = tool_name (registry id — same value from envelope.tool_name)
            # tool_name and tool_id carry the same value in V1; tool_id is the
            # registry capability id, which == envelope.tool_name at wrap time.
            "tool_id": envelope.tool_name,
            "tool_name": envelope.tool_name,
            "tool_version": envelope.tool_version,
            "outcome_class": envelope.outcome_class,
            "success": envelope.success,
            "confidence": envelope.confidence,
            "freshness_seconds": envelope.freshness_seconds,
            "registry_snapshot_hash": envelope.registry_snapshot_hash,
            "generated_at": envelope.generated_at.isoformat(),
            "len_failure_modes": len(envelope.failure_modes),
            "len_normalization_warnings": len(envelope.normalization_warnings),
            "len_citations": len(envelope.citations),
        }
        _logger.info(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001 — telemetry NEVER blocks tool execution
        _fallback_logger.warning("envelope telemetry emit failed: %s", exc)
