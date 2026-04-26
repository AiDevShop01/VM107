"""Test FaissBackend implementation."""

import pytest
from plugins._memory.backend.faiss_backend import FaissBackend


@pytest.mark.asyncio
async def test_faiss_backend_wraps_existing_behavior():
    """FaissBackend should wrap existing MyFaiss behavior."""
    # This test validates that FaissBackend can be instantiated
    # and implements the Protocol - actual FAISS logic is preserved as-is
    backend = FaissBackend(agent=None)

    # Should have Protocol methods
    assert hasattr(backend, "add")
    assert hasattr(backend, "search")
    assert hasattr(backend, "delete")
    assert hasattr(backend, "clear")
