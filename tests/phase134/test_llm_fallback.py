"""SC-2 LLM keystone RED gate — primary-down acompletion must bound + recover on the secondary.

Phase 134 Wave 0 (Nyquist RED-first). This encodes the exact live-hang incident: the primary
provider becomes unreachable and the agent turn must bound in time and recover on the Gemini
secondary rather than hanging or dying.

It builds a real `LiteLLMChatWrapper` via `models.get_chat_model` (so the Wave 1
`_merge_provider_defaults` timeout/fallback injection lands automatically), monkeypatches
`models.acompletion` so the PRIMARY model raises litellm `ServiceUnavailableError`, and asserts:

  (1) `unified_call` returns a successful result sourced from the SECONDARY model (D-03 recovery),
  (2) total wall-clock <= A0_LLM_TIMEOUT (30s) x a small factor — the custom retry loop must not
      compound timeout x num_retries x fallbacks (D-04),
  (3) the shared SourceHealthRegistry records the primary provider as unavailable (degrade signal).

MUST FAIL today (RED): no timeout/fallback is injected, the custom `unified_call` retry loop
re-hits the SAME down model and re-raises, and no health signal is emitted. Wave 1 (134-03)
injects `timeout`/`num_retries`/dict-form `fallbacks` and neutralises the custom retry
(`a0_retry_attempts` default 0) to turn this green.

The canonical primary-down health id Wave 1 must emit is ``"llm_primary"`` (the gate also
accepts ``"llm"`` or the provider name for latitude).
"""
import asyncio
import os
import sys
import time

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

PRIMARY_PROVIDER = "deepseek"
PRIMARY_MODEL_NAME = "deepseek-chat"
SECONDARY_MODEL = os.getenv("A0_LLM_SECONDARY_MODEL", "gemini/gemini-2.0-flash")
SECONDARY_CONTENT = "SECONDARY_PROVIDER_OK"
ACCEPTABLE_PRIMARY_HEALTH_IDS = ("llm_primary", "llm", PRIMARY_PROVIDER)
LLM_TIMEOUT_BOUND = float(os.getenv("A0_LLM_TIMEOUT", "30")) * 2.0


def _build_fake_acompletion(primary_model: str, called: list):
    """Fake acompletion: primary raises ServiceUnavailableError unless a fallback is configured;
    the secondary (or a litellm-native dict-form fallback) returns a minimal success."""
    from litellm.exceptions import ServiceUnavailableError

    async def fake_acompletion(*args, **kwargs):
        model = kwargs.get("model")
        fallbacks = kwargs.get("fallbacks")
        called.append(model)

        # Secondary invoked directly (wrapper-level failover path).
        if model and model != primary_model:
            return {"choices": [{"message": {"content": SECONDARY_CONTENT}}]}

        # Primary path.
        if fallbacks:
            # litellm-native failover: honour the first configured dict-form fallback.
            fb = fallbacks[0]
            fb_model = fb.get("model") if isinstance(fb, dict) else fb
            called.append(fb_model)
            return {"choices": [{"message": {"content": SECONDARY_CONTENT}}]}

        # TODAY: no fallback configured -> the injected primary outage surfaces.
        try:
            raise ServiceUnavailableError(
                message="injected primary outage",
                llm_provider=PRIMARY_PROVIDER,
                model=primary_model,
            )
        except TypeError:
            raise ServiceUnavailableError("injected primary outage")

    return fake_acompletion


def test_primary_down_recovers_on_secondary_bounded_with_signal(monkeypatch):
    import models
    from emitters.source_health_registry import SourceHealthRegistry

    monkeypatch.setenv("A0_LLM_SECONDARY_MODEL", SECONDARY_MODEL)
    SourceHealthRegistry.get_shared_instance().clear()

    wrapper = models.get_chat_model(PRIMARY_PROVIDER, PRIMARY_MODEL_NAME)
    primary_model = wrapper.model_name
    called: list = []
    monkeypatch.setattr(models, "acompletion", _build_fake_acompletion(primary_model, called))

    async def _drive():
        return await wrapper.unified_call(
            system_message="You are a test.",
            user_message="ping",
        )

    outcome: dict = {"response": None, "exc": None}
    start = time.monotonic()
    try:
        response, _reasoning = asyncio.run(_drive())
        outcome["response"] = response
    except Exception as exc:  # noqa: BLE001 — capture; primary-down must not surface uncaught
        outcome["exc"] = exc
    elapsed = time.monotonic() - start

    failures: list[str] = []

    # (1) secondary-sourced success.
    if outcome["response"] != SECONDARY_CONTENT:
        failures.append(
            f"expected secondary-sourced response {SECONDARY_CONTENT!r}, got "
            f"{outcome['response']!r} "
            f"(exc={type(outcome['exc']).__name__ if outcome['exc'] else None})"
        )
    if SECONDARY_MODEL not in called:
        failures.append(
            f"secondary model {SECONDARY_MODEL!r} was never called; call sequence={called}"
        )

    # (2) bounded wall-clock (no custom-retry x fallback compounding).
    if elapsed > LLM_TIMEOUT_BOUND:
        failures.append(f"unified_call took {elapsed:.1f}s (> {LLM_TIMEOUT_BOUND:.0f}s bound)")

    # (3) primary-down health signal.
    snap = SourceHealthRegistry.get_shared_instance().snapshot()
    primary_down = any(
        sid in snap and snap[sid].available is False
        for sid in ACCEPTABLE_PRIMARY_HEALTH_IDS
    )
    if not primary_down:
        failures.append(
            "no primary-down health signal recorded; expected one of "
            f"{ACCEPTABLE_PRIMARY_HEALTH_IDS} marked unavailable, snapshot keys={list(snap)}"
        )

    assert not failures, "SC-2 LLM RED:\n  " + "\n  ".join(failures)
