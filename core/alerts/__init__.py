"""Phase 89 Wave 3 — Core alerts package.

Provides the shared Phase 89↔Phase 91 contract surface.

Exports:
  - emit_alert_candidate: Shared entry point for contradiction + discovery alert emission.
                          Wave 4 discovery agent also imports from this package.
"""
from .phase91_emit import emit_alert_candidate

__all__ = ["emit_alert_candidate"]
