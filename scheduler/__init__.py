"""VM107 scheduler package — Phase 67 Plan 13.

Operational scheduler scripts that iterate opted-in accounts, call the
matching emitter's ``get_*()`` method, and route through
``persist_and_publish()`` to land on the WS topic.

Each scheduler script is intentionally idempotent and exception-safe:
one account's failure must not propagate to subsequent accounts (Pitfall 7
parallel — per-account isolation).

Cron times are env-driven (Phase 47.3 lock — no fallback defaults):
  - ``VM107_MORNING_BRIEF_CRON``    (typical: ``0 7 * * *``)
  - ``VM107_OVERNIGHT_DELTA_CRON``  (typical: ``30 6 * * *``)
  - ``VM107_REFLECTION_PROMPT_TRIGGER``  (event-driven; CLOSE-state entry)

Schedulers are import-safe — top-level imports do not call into Django
or external services so the modules can be discovered by Dagster /
cron / pytest without side effects.
"""
