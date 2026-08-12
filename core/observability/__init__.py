"""Observability primitives for VM107 (Phase 139 / P7).

Currently exposes the SLORegistry — the in-app p50/p95 SLO capture singleton
(D-01). Percentiles are computed in-process from bounded per-path ring buffers
and surfaced through the existing telemetry/health surfaces.
"""
