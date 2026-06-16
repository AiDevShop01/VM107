"""Wave 5 Dagster asset materialisation test.

Phase 87 Wave 5 — Task 3. Verifies belief_weekly_decay materialises against a
mocked BeliefStore + that the BeliefStore import lives INSIDE the asset function
(env-fail-fast at run time, not at code_location boot).
"""
import os
import pathlib
import sys

import pytest

# The Dagster code lives in a sibling repo — import path must include the
# fingpt_orchestration src dir before pytest tries to import the asset module.
DAGSTER_SRC = pathlib.Path(
    "/Volumes/ HardDrive/FinGPT/Dagster/fingpt_orchestration/src"
)
if str(DAGSTER_SRC) not in sys.path:
    sys.path.insert(0, str(DAGSTER_SRC))

# Sibling Dagster modules (macro_fred_calendar) do `os.environ["VM101_API_URL"]`
# at module import time. Provide dummy values so the import chain succeeds when
# running these unit tests outside the Dagster container. The belief_weekly_decay
# asset itself does NOT touch these vars.
os.environ.setdefault("VM101_API_URL", "http://localhost-unit-test:8001")
os.environ.setdefault("VM100_API_URL", "http://localhost-unit-test:8000")
os.environ.setdefault("VM100_INTERNAL_BASE_URL", "http://localhost-unit-test:8000")
os.environ.setdefault("VM102_API_URL", "http://localhost-unit-test:8003")
os.environ.setdefault("VM109_API_URL", "http://localhost-unit-test:8002")
os.environ.setdefault("VM109_API_KEY", "unit-test-not-secret")
os.environ.setdefault("GARMIN_OWNER_ACCOUNT_ID", "1")

pytestmark = pytest.mark.phase_87


def _load_belief_weekly_decay_module():
    """Load the asset module via importlib to bypass the
    `fingpt_orchestration.assets` package __init__ side effects (which
    instantiate the full asset registry + trigger fred_schedules HTTP retries).
    """
    import importlib.util

    asset_file = (
        DAGSTER_SRC / "fingpt_orchestration" / "assets" / "governance"
        / "belief_weekly_decay.py"
    )
    spec = importlib.util.spec_from_file_location(
        "belief_weekly_decay_isolated", str(asset_file)
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_asset_invokes_belief_store_and_emits_metadata():
    """Invoke the asset's underlying compute function directly.

    Bypasses `dagster.materialize(...)` (which would instantiate the full
    Definitions object + trigger fred_schedules HTTP retry loops). Also
    bypasses the parent `fingpt_orchestration.assets` package __init__ by
    loading the asset module via importlib.util.

    Patches the BeliefStore at the source module — the asset imports it
    INSIDE the function body, so the lookup happens at call time against the
    source module, NOT the asset module (which is exactly what the lazy-import
    lock test asserts).
    """
    from unittest.mock import MagicMock, patch

    from dagster import build_asset_context

    module = _load_belief_weekly_decay_module()
    belief_weekly_decay = module.belief_weekly_decay

    fake_bs = MagicMock()
    fake_bs.apply_weekly_decay_to_all_active.return_value = {
        "decayed": 7,
        "retired": 1,
    }
    with patch(
        "VM107.core.belief.belief_store.BeliefStore",
        return_value=fake_bs,
    ):
        ctx = build_asset_context()
        # Invoke the AssetsDefinition directly — Dagster supports calling
        # an @asset-decorated function as a regular Python callable for
        # unit testing (returns the wrapped Output).
        result = belief_weekly_decay(ctx)
    # Output(value=None, metadata={...}) — Dagster returns the Output object;
    # int metadata is wrapped in IntMetadataValue, so unwrap via .value
    assert result.value is None
    assert "decayed" in result.metadata
    assert "retired" in result.metadata
    decayed_meta = result.metadata["decayed"]
    retired_meta = result.metadata["retired"]
    # Dagster may wrap int metadata in IntMetadataValue or pass it through
    decayed_val = getattr(decayed_meta, "value", decayed_meta)
    retired_val = getattr(retired_meta, "value", retired_meta)
    assert decayed_val == 7
    assert retired_val == 1
    fake_bs.apply_weekly_decay_to_all_active.assert_called_once()


def test_asset_imports_belief_store_lazily():
    """Per project Dagster pattern — BeliefStore import inside the asset
    function so env-fail-fast happens at run time, not at code_location boot.

    Source-inspection only; avoids importing the whole Dagster asset registry
    (which would 5x60s retry-loop the fred_schedules HTTP call against the
    unit-test host placeholder).
    """
    module_src = (
        DAGSTER_SRC / "fingpt_orchestration" / "assets" / "governance"
        / "belief_weekly_decay.py"
    ).read_text()
    # Import must appear in the file (otherwise the asset can't use it)
    assert "from VM107.core.belief.belief_store import BeliefStore" in module_src
    # Every `from VM107` line must be indented (inside a function body),
    # never at module top level
    for line in module_src.splitlines():
        if "from VM107" in line:
            assert line.startswith("    "), (
                f"BeliefStore import must be inside function — env-fail-fast at "
                f"run time. Offending line: {line!r}"
            )
