"""Phase 86 Wave-3 placeholder conftest for VM107 macro_historical_analyst tests.

TODO (Wave-3, Plan 86-07+): Drop macro_historical_analyst agent fixtures here:
  - macro_agent_fixture: spawns a sandboxed Phase 86 macro analyst agent
  - historical_impact_fixture: pre-seeded CPI/Gold/SPX impact results for replay
  - agent_tool_mock_fixture: mocks event-study + correlation VM102 endpoints

For now this file exists so Wave-1/Wave-2 plans can reference tests/phase86/
as a drop-in target without an ImportError.
"""

import pytest

pytestmark = pytest.mark.phase_86
