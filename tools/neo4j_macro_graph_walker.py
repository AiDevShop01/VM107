"""Phase 87 Wave 2 — Macro Graph Walker tool.

Implements the contract declared in
``VM107/registry/tool/vm105.neo4j_macro_graph_walker.yaml`` (shipped in Plan
87-03 ahead of this implementation per the distributed-registry-YAML lock).

Per Phase 39 typed-API lock VM107 never bolt://s directly to Neo4j; this
tool calls a VM100-hosted internal endpoint that wraps the Cypher MATCH
walk (AFFECTS*1..N + DRIVES UNION per ARCHITECTURE § 3.4).

Per project lock:
  - NO ``os.getenv("X", "default")`` patterns — fail fast on missing env.
  - NO hardcoded URLs — base URL comes from env var or explicit arg.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import httpx


@dataclass(frozen=True)
class Hop:
    """One edge in the transmission chain.

    Attributes mirror the response payload of the VM100 graph-walk endpoint:
      - source / target  — node ids (MacroIndicator.id or Asset.symbol)
      - relationship_type — "AFFECTS" or "DRIVES"
      - strength          — signed for AFFECTS, unsigned for DRIVES
      - confidence        — [0.0, 1.0]
      - sample_size       — observations behind the edge
      - evidence_period   — ISO date range "YYYY-MM-DD/YYYY-MM-DD"
      - hop_order         — 0-indexed AFFECTS hop; None for DRIVES terminals
    """

    source: str
    target: str
    relationship_type: str
    strength: float
    confidence: float
    sample_size: int
    evidence_period: str
    hop_order: Optional[int]


class Neo4jMacroGraphWalker:
    """Walks the VM105 Neo4j macro graph via the VM100 internal endpoint.

    Example:
        >>> walker = Neo4jMacroGraphWalker()  # picks up VM100_INTERNAL_BASE_URL
        >>> hops = walker.walk("CPIAUCSL", max_hops=5)
        >>> for hop in hops:
        ...     print(hop.source, "→", hop.target, hop.relationship_type)
    """

    def __init__(
        self,
        vm100_internal_base_url: Optional[str] = None,
        *,
        timeout_s: float = 0.5,
    ) -> None:
        url = vm100_internal_base_url or os.environ.get("VM100_INTERNAL_BASE_URL")
        if not url:
            raise RuntimeError(
                "VM100_INTERNAL_BASE_URL required — env-driven, no default "
                "(CLAUDE.md no-fallback-defaults lock)"
            )
        self._base = url.rstrip("/")
        self._client = httpx.Client(timeout=timeout_s)

    def walk(self, indicator_id: str, max_hops: int = 5) -> list[Hop]:
        """Walk the graph starting from ``indicator_id``.

        Args:
            indicator_id: FRED-style indicator id (UNIQUE :MacroIndicator.id).
            max_hops: Maximum AFFECTS chain length to traverse (1..5).

        Returns:
            Ordered list of Hop dataclasses — AFFECTS edges first (ordered by
            ``hop_order``), then DRIVES terminals (``hop_order=None``).

        Raises:
            httpx.HTTPStatusError: VM100 endpoint returned 4xx/5xx.
        """
        url = f"{self._base}/api/macro/internal/graph-walk/{indicator_id}"
        resp = self._client.get(url, params={"max_hops": max_hops})
        resp.raise_for_status()
        payload = resp.json()
        return [Hop(**h) for h in payload["hops"]]

    def close(self) -> None:
        """Release the underlying httpx client. Idempotent."""
        try:
            self._client.close()
        except Exception:  # noqa: BLE001
            pass
