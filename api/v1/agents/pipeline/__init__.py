"""Phase 48 Plan 48-09 — refinement-pipeline HTTP endpoint package.

POST /api/v1/agents/pipeline/refine accepts a Hypothesis id and dispatches
a bounded refinement loop via the Phase 42 scheduler.

CONTEXT § Decisions 16 (entry surface) + 17 (async-only) + 18 (sole emitter):
the endpoint emits ``refinement_loop_started`` BEFORE returning 202 — this
is the only refinement event the HTTP entry surface emits; ``main_loop``
emits the rest from the worker context.
"""
