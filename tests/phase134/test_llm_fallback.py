"""SC-2 LLM keystone (GREEN) — primary-down acompletion must BOUND + recover on the secondary.

Phase 134-09 (WR-07). Encodes the live-hang incident AND proves the anti-compounding fix: the
primary provider becomes unreachable and the agent turn must bound in time and recover on the
Gemini secondary rather than hanging or dying.

It builds a real `LiteLLMChatWrapper` via `models.get_chat_model` (so `_merge_provider_defaults`
timeout/fallback injection lands automatically) and monkeypatches `models.acompletion` with a
SLEEPING fake so the bound is measurable (the earlier RED fake raised instantly, making the
bound assertion vacuous — the exact WR-07 finding). It asserts:

  (1) `unified_call` returns a result sourced from the SECONDARY model (D-03 recovery),
  (2) a REAL numeric bound: the sleeping fake proves the primary paid only ONE timeout because
      the wrapper popped `num_retries` (WR-07) — strictly less than the un-popped
      `(1+num_retries) x timeout` compounding (D-04),
  (3) the shared SourceHealthRegistry records the primary provider as unavailable.

The fallback list is injected via `A0_LLM_FALLBACKS` (JSON) so GREEN is deterministic regardless
of ambient `API_KEY_GOOGLE`/`GOOGLE_API_KEY` (the earlier env-coupling finding). The canonical
primary-down health id is ``"llm_primary"`` (the gate also accepts ``"llm"`` or the provider
name for latitude).
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
SECONDARY_MODEL = "gemini/gemini-2.0-flash"
SECONDARY_CONTENT = "SECONDARY_PROVIDER_OK"
ACCEPTABLE_PRIMARY_HEALTH_IDS = ("llm_primary", "llm", PRIMARY_PROVIDER)

# WR-07: run the whole test on a SMALL real timeout so the sleeping fake makes the
# anti-compounding bound MEASURABLE (the old fake raised instantly, so elapsed was ~0ms
# and the "bound" assertion was vacuous). A0_LLM_TIMEOUT is set via monkeypatch below.
TEST_TIMEOUT_S = 1.0


def _build_fake_acompletion(primary_model: str, called: list, timeout_s: float):
    """Fake acompletion that MODELS litellm's per-call retry via ``num_retries``.

    The PRIMARY path sleeps ``timeout_s`` once per litellm-native attempt — i.e.
    ``1 + num_retries`` times — THEN raises a transient error, so the real compounding is
    observable in wall-clock. The wrapper's WR-07 fix pops ``num_retries`` off the primary
    call, so with the fix the primary pays 1 x timeout; WITHOUT it, it would pay
    ``(1 + num_retries) x timeout``. The SECONDARY (wrapper-level failover) returns instantly.
    """
    from litellm.exceptions import ServiceUnavailableError

    async def fake_acompletion(*args, **kwargs):
        model = kwargs.get("model")
        called.append(model)

        # Secondary invoked directly by the wrapper-level failover path — instant success.
        if model and model != primary_model:
            return {"choices": [{"message": {"content": SECONDARY_CONTENT}}]}

        # Primary path: emulate litellm doing (1 + num_retries) attempts, each paying timeout.
        num_retries = int(kwargs.get("num_retries", 0) or 0)
        for _ in range(1 + num_retries):
            await asyncio.sleep(timeout_s)
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
    import json

    import models
    from emitters.source_health_registry import SourceHealthRegistry

    # Deterministic, ambient-credential-independent fallback (WR-07 env-coupling fix): inject
    # A0_LLM_FALLBACKS JSON so _build_llm_fallbacks() returns a fixed secondary regardless of
    # API_KEY_GOOGLE / GOOGLE_API_KEY being present in the runner.
    monkeypatch.setenv("A0_LLM_SECONDARY_MODEL", SECONDARY_MODEL)
    monkeypatch.setenv("A0_LLM_TIMEOUT", str(TEST_TIMEOUT_S))
    monkeypatch.setenv("A0_LLM_NUM_RETRIES", "1")
    monkeypatch.setenv(
        "A0_LLM_FALLBACKS",
        json.dumps([{"model": SECONDARY_MODEL, "api_key": "test-secondary-key"}]),
    )
    SourceHealthRegistry.get_shared_instance().clear()

    wrapper = models.get_chat_model(PRIMARY_PROVIDER, PRIMARY_MODEL_NAME)
    primary_model = wrapper.model_name
    called: list = []
    monkeypatch.setattr(
        models, "acompletion", _build_fake_acompletion(primary_model, called, TEST_TIMEOUT_S)
    )

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

    # (2) REAL numeric bound. The sleeping fake really slept (>= ~1 x timeout), proving the
    # assertion is not vacuous; and with num_retries POPPED the primary paid only ONE timeout
    # (~1s), STRICTLY LESS than the un-popped compounded worst case ((1+num_retries) x timeout
    # on the primary alone = ~2s). A margin absorbs failover + event-loop overhead.
    if elapsed < TEST_TIMEOUT_S * 0.8:
        failures.append(
            f"unified_call returned in {elapsed:.2f}s (< {TEST_TIMEOUT_S * 0.8:.2f}s); the fake "
            f"did not actually sleep — the bound would be vacuous"
        )
    popped_bound = TEST_TIMEOUT_S * 1.8  # ~1x timeout + margin; un-popped ~2x would fail
    if elapsed >= popped_bound:
        failures.append(
            f"unified_call took {elapsed:.2f}s (>= {popped_bound:.2f}s); num_retries was NOT "
            f"popped off the primary call — the failover path is compounding (WR-07)"
        )

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

    assert not failures, "WR-07 bounded-failover:\n  " + "\n  ".join(failures)
