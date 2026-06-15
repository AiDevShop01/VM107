"""Phase 86 Plan 07 — macro_historical_analyst event-driven agent.

Event-driven single-emit-terminate agent. Receives the vm102_event_study envelope,
emits a <=50-word factual narrative citing N + period, writes CoT trail to Phase 70.5
WORM table (agent_cot_trail), then terminates.

Locked decisions (CONTEXT.md):
- D5: event-driven, NOT scheduled, NOT background loop
- D7: no Brain B5/B6/B9/B13 absorbed; pure factual narration
- ARCHITECTURE §6: hard assertion — narrative MUST contain str(N) AND period substring

Hard-assertion flow:
1. Make LLM call
2. Regex-assert narrative contains N AND period
3. If missing: re-prompt ONCE with explicit instruction
4. If still missing: return error envelope (confidence='low', code='MissingCitations')

CoT trail: written to agent_cot_trail via services.cot_writer (Phase 70.5 WORM).
Trail length cap: 30 events per invocation (prevents runaway reasoning loops).
"""
from __future__ import annotations

import re
import time
import uuid

from services.cot_writer import write_cot_trail
from services.llm_client import call_llm
from agents.macro_historical_analyst.prompt import build_prompt

COT_MAX_EVENTS = 30  # ARCHITECTURE §6 trail length cap


class MacroHistoricalAnalyst:
    """Event-driven agent: receives event-study envelope -> emits <=50-word narrative -> terminates.

    No background loop, no scheduling, no Brain B5/B6/B9/B13 (CONTEXT D7).
    Reuses Phase 85 single-emit-terminate lifecycle pattern.
    """

    agent_id = "macro_historical_analyst"

    def invoke(
        self,
        envelope: dict,
        indicator_name: str,
        asset_names: list[str],
        result: dict,
    ) -> dict:
        """Invoke the agent synchronously.

        Args:
            envelope:       The vm102_event_study envelope (must contain provenance
                            with sample_size and period).
            indicator_name: Human-readable indicator name.
            asset_names:    Ordered list of asset display names.
            result:         The result dict from the event-study response.

        Returns:
            Output envelope dict:
            {
                "envelope": {
                    "tool_id": "vm107_macro_historical_analyst",
                    "confidence": "high"|"medium"|"low",
                    "provenance": {"sample_size": N, "period": "...", "indicator_id": "..."},
                    "latency_ms": int,
                },
                "result": {"narrative": str} | None,
                "error": None | {"code": str, "meta": {...}},
            }

        Raises:
            KeyError: If envelope.provenance is missing sample_size or period.
            RuntimeError: If CoT trail exceeds COT_MAX_EVENTS (runaway prevention).
        """
        t0 = time.time()
        invocation_id = str(uuid.uuid4())
        cot_events: list[dict] = []

        # Validate envelope shape — raises KeyError if malformed (per spec)
        self._validate_envelope(envelope)

        prov = envelope["provenance"]
        n: int = prov["sample_size"]
        period: str = prov["period"]
        indicator_id: str = prov.get("indicator", "")

        try:
            # Build prompt and make initial LLM call
            prompt = build_prompt(envelope, indicator_name, asset_names, result)
            cot_events.append({"role": "prompt", "text": prompt})

            narrative = call_llm(prompt)
            cot_events.append({"role": "emit", "text": narrative})

            # Hard assertion: narrative MUST cite N and period (ARCHITECTURE §6)
            missing = self._missing_citations(narrative, n, period)
            if missing:
                # Re-prompt ONCE with explicit citation instruction
                reprompt = (
                    f"{prompt}\n\n"
                    f"CRITICAL: Your previous response omitted required citations: {missing}.\n"
                    f"You MUST include N={n} and period={period} verbatim in your response.\n"
                    f"Re-emit your <=50-word paragraph now, ensuring both N={n} and "
                    f"period={period} appear in the text."
                )
                cot_events.append({"role": "reprompt", "text": reprompt})
                narrative = call_llm(reprompt)
                cot_events.append({"role": "emit_2", "text": narrative})
                missing = self._missing_citations(narrative, n, period)

                if missing:
                    # Both attempts failed — emit error envelope (confidence='low')
                    write_cot_trail(
                        self.agent_id,
                        invocation_id,
                        cot_events,
                        terminated_at=time.time(),
                    )
                    return {
                        "envelope": {
                            "tool_id": "vm107_macro_historical_analyst",
                            "confidence": "low",
                            "provenance": {
                                "sample_size": n,
                                "period": period,
                                "indicator_id": indicator_id,
                            },
                            "latency_ms": int((time.time() - t0) * 1000),
                        },
                        "result": None,
                        "error": {
                            "code": "MissingCitations",
                            "meta": {"missing": missing},
                        },
                    }

            # Guard: CoT trail length cap (prevents runaway reasoning)
            if len(cot_events) > COT_MAX_EVENTS:
                raise RuntimeError(
                    f"CoT trail exceeded {COT_MAX_EVENTS} events — runaway reasoning prevented"
                )

            # Write CoT trail to Phase 70.5 WORM (observability — never raises)
            write_cot_trail(
                self.agent_id,
                invocation_id,
                cot_events,
                terminated_at=time.time(),
            )

            # Confidence: high if N > 20 (meaningful sample), medium otherwise
            confidence = "high" if n > 20 else "medium"

            return {
                "envelope": {
                    "tool_id": "vm107_macro_historical_analyst",
                    "confidence": confidence,
                    "provenance": {
                        "sample_size": n,
                        "period": period,
                        "indicator_id": indicator_id,
                    },
                    "latency_ms": int((time.time() - t0) * 1000),
                },
                "result": {"narrative": narrative},
                "error": None,
            }

        except (RuntimeError, KeyError):
            # Re-raise fatal errors (KeyError = malformed input, RuntimeError = trail cap)
            raise

    @staticmethod
    def _missing_citations(narrative: str, n: int, period: str) -> list[str]:
        """Check whether the narrative contains both N and period.

        Args:
            narrative: The LLM-generated narrative string.
            n:         The sample size integer that must appear as a word boundary match.
            period:    The period string (e.g. "1990-2025") that must appear as a substring.

        Returns:
            List of missing citation keys. Empty list means all citations present.
        """
        missing = []
        # Check N appears as a word-boundary integer (not as part of a larger number)
        if not re.search(rf"\b{n}\b", narrative):
            missing.append("sample_size")
        # Check period appears as an exact substring
        if period not in narrative:
            missing.append("period")
        return missing

    @staticmethod
    def _validate_envelope(envelope: dict) -> None:
        """Validate the envelope has the required provenance fields.

        Args:
            envelope: The input envelope dict.

        Raises:
            KeyError: If provenance is missing or sample_size/period not present.
        """
        prov = envelope.get("provenance") or {}
        if "sample_size" not in prov or "period" not in prov:
            raise KeyError(
                "envelope.provenance missing required fields: "
                f"sample_size={'present' if 'sample_size' in prov else 'MISSING'}, "
                f"period={'present' if 'period' in prov else 'MISSING'}"
            )
