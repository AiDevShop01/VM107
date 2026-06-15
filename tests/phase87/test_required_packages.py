"""Wave 0 startup-time regression — Wave 4/5 sibling services import these at boot.

If any of these imports fail, Wave 4 macro_story_tracker / Wave 5
macro_regime_monitor would die with ModuleNotFoundError at scheduler startup.
Fail-fast at test time beats first scheduler tick.
"""
from importlib.metadata import version as _pkg_version

import pytest
from packaging.version import Version

pytestmark = pytest.mark.phase_87


def _installed(pkg: str) -> Version:
    """Resolve installed package version via importlib.metadata (not module __version__).

    qdrant-client does NOT expose `__version__` at module level, so reading
    distribution metadata is the only reliable cross-package way.
    """
    return Version(_pkg_version(pkg))


def test_apscheduler_importable():
    import apscheduler  # noqa: F401
    from apscheduler.schedulers.blocking import BlockingScheduler  # noqa: F401

    assert _installed("apscheduler") >= Version("3.10")


def test_qdrant_client_importable():
    import qdrant_client  # noqa: F401
    from qdrant_client import QdrantClient  # noqa: F401

    assert _installed("qdrant-client") >= Version("1.7")


def test_neo4j_driver_importable():
    import neo4j  # noqa: F401
    from neo4j import GraphDatabase  # noqa: F401

    assert _installed("neo4j") >= Version("5.15")


def test_simpleeval_importable():
    import simpleeval  # noqa: F401
