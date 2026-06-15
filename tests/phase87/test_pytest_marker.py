"""Wave 0 regression guard — confirms the phase_87 marker is registered.

Per project lock: no os.getenv("X", "default") patterns, no hardcoded URLs.
This file deliberately uses only subprocess + pathlib + pytest — fail-fast if the
marker is ever lost from pytest.ini.
"""
import pathlib
import subprocess

import pytest

pytestmark = pytest.mark.phase_87


def test_phase87_marker_registered():
    """If this fails, pytest.ini was edited and lost the marker — re-add it."""
    result = subprocess.run(
        ["pytest", "--markers"],
        capture_output=True,
        text=True,
        cwd=pathlib.Path(__file__).parent.parent.parent,
    )
    assert "phase_87" in result.stdout, (
        "phase_87 marker not registered — see pytest.ini markers section"
    )
