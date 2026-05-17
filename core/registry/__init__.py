"""VM107 capability registry runtime.

The public surface is CapabilityRegistry (singleton). All other modules
in this package are internal implementation details.

Usage in VM107 boot path:
    import os
    from pathlib import Path
    from core.registry.capability_registry import CapabilityRegistry

    CapabilityRegistry.initialize(Path(os.environ["CAPABILITY_REGISTRY_ROOT"]))

After boot any module can call:
    from core.registry.capability_registry import CapabilityRegistry
    reg = CapabilityRegistry.get()
"""

# NOTE: CapabilityRegistry is NOT imported here at package level to avoid
# circular imports during test collection. Import it directly:
#   from core.registry.capability_registry import CapabilityRegistry
