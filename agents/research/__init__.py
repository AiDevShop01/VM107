"""Phase 92 Plan 03 — VM107 research agents subpackage.

Houses the hybrid indicator linker (synonym + LLM fallback), the deterministic
asset linker, and the ResearchClassificationAgent that orchestrates them.

Why VM107 (not VM101): the indicator linker's Stage 2 calls into the VM107
LLM dispatch path (services/llm_client.py). Keeping the linker close to
LLM dispatch avoids a cross-VM hop on every soft-reject candidate.
"""
