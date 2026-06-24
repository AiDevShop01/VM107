"""POST /api/v1/events/emit — Phase 90 fix-forward 2026-06-24.

Receives event envelopes from Dagster forecast nightly assets
(cpd_nightly emits forecast_regime_change_detected). Phase 91 alert
engine will replace the stub body with the actual alert pipeline
(emit-to-message-bus + topic dispatch + subscriber fanout); this stub
unblocks the upstream wiring so Dagster materializations report
events_emitted > 0 instead of swallowing 404s.

Payload contract (forecast_regime_change_detected variant):
    {
      "event_type":  "forecast_regime_change_detected",
      "event_id":    "<uuid4>",
      "indicator_id": "FEDFUNDS",
      "breakpoints":  [15, 47],
      "detected_at":  "2026-06-24T00:11:32+00:00"
    }

Auth: X-API-KEY (VM107_INTERNAL_TOKEN) — Phase 73-followup service-auth
lock. Loopback NOT required because Dagster calls land here via
host.docker.internal (Docker bridge, not 127.0.0.1).
"""

from helpers.api import ApiHandler, Request, Response
from helpers.print_style import PrintStyle


_REQUIRED_FIELDS = ("event_type", "event_id")


class EventsEmit(ApiHandler):
    """Accept inbound event envelopes from internal services."""

    @classmethod
    def requires_auth(cls) -> bool:
        return False

    @classmethod
    def requires_csrf(cls) -> bool:
        return False

    @classmethod
    def requires_api_key(cls) -> bool:
        return True

    @classmethod
    def get_methods(cls) -> list[str]:
        return ["POST"]

    async def process(self, input: dict, request: Request) -> dict | Response:
        for field in _REQUIRED_FIELDS:
            if not input.get(field):
                return Response(
                    response=(
                        '{"error": "Missing required field: ' + field + '"}'
                    ),
                    status=400,
                    content_type="application/json",
                )

        PrintStyle().print(
            f"[vm107.events.emit] event_type={input.get('event_type')!r} "
            f"event_id={input.get('event_id')!r} "
            f"indicator_id={input.get('indicator_id')!r}"
        )

        return {
            "accepted": True,
            "event_id": input["event_id"],
        }
