"""VM107 emitter contracts (Phase 67 Plan 06).

Pydantic v2 typed contracts produced by VM107 emitters and consumed by VM100
via the chokepoint clients in VM100/backend/mission_control/clients/.

Each contract is frozen + extra=forbid so consumers can rely on shape stability.
"""
from emitters.contracts.morning_brief import MorningBriefContract  # noqa: F401

# Task 2 contracts (overnight_delta) added in the same plan; tolerate missing
# during the Task 1 RED → GREEN window.
try:  # pragma: no cover - import shape check
    from emitters.contracts.overnight_delta import (  # noqa: F401
        BucketDelta,
        OvernightDeltaContract,
    )
except ImportError:
    pass
