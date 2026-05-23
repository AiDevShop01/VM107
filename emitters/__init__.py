"""
VM107 emitters package — Phase 66.

All emitters in this package are shared across VM107 sub-agents.
Each emitter follows the deterministic-first architecture lock (CONTEXT.md §2):
pure computation first, LLM enrichment second (and only when novelty > threshold).
"""
