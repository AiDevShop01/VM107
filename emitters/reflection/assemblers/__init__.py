"""Progressive enrichment assemblers (4 stages — Phase 67 Plan 07).

Each assembler produces a list of frozen dataclasses representing one
enrichment layer. Assemblers are pure (no side effects beyond their
injected VM100 chokepoint client) and degrade gracefully on missing
upstream data — returning an empty list while recording the failure in
``missing_sources``.

Intermediate types are FROZEN DATACLASSES (not Pydantic) because they
are internal pipeline state, never crossing a wire boundary. The wire
contract is ``ReflectionPromptContract`` (in
``emitters/contracts/reflection_prompt.py``).
"""

from emitters.reflection.assemblers.trade_observation import (  # noqa: F401
    TradeObservation,
    TradeObservationAssembler,
)
from emitters.reflection.assemblers.behavioral_interpretation import (  # noqa: F401
    BehavioralInterpretation,
    BehavioralInterpretationAssembler,
)
from emitters.reflection.assemblers.pattern_context import (  # noqa: F401
    PatternContext,
    PatternContextAssembler,
)
from emitters.reflection.assemblers.longitudinal_context import (  # noqa: F401
    LongitudinalContext,
    LongitudinalContextAssembler,
)
