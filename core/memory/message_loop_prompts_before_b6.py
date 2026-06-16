"""Phase 87 Wave 4a — Brain B6 RAG injection helper.

Per Brain Part 2 §B6 verbatim format. Injects top-K similar past macro
episodes into the agent's prompt before the main user message.

Output shape (Brain Part 2 §B6 verbatim)::

    ## Relevant prior episodes
    1. [ref:episode:<id-1>] On 2022-03-10 CPI printed 7.9% (surprise +0.3)...
    2. [ref:episode:<id-2>] On 2022-04-12 CPI printed 8.5% (surprise +0.2)...
    ...

Empty retrieval emits an explicit '(no relevant prior episodes)' line — never
an empty string — so the LLM cannot hallucinate a context it didn't receive.

NOTE on naming: the plan-of-record refers to this as the
``message_loop_prompts_before`` hook (per Brain Part 2 §B6) but it is wired
into agent code as a plain function call, not as an auto-discovered VM107
``extensions/python/message_loop_prompts_before/`` Extension subclass. The
distinction matters: Phase 87 macro agents call this helper imperatively
from their analysis step (so the retrieved episodes only enter the prompt
the agent is about to assemble, not every message in the loop). Plan 87-08
wires the story tracker; Plan 87-04 already wires the transmission analyst
via the episodic_memory_service shim (the call site is unchanged).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from VM107.core.memory.episodic_memory_service import (
    EpisodicMemoryService,
    EpisodicQuery,
)


def message_loop_prompts_before_b6(
    *,
    agent_profile_id: str,
    query_text: str,
    episodic_memory_service: EpisodicMemoryService,
    top_k: int = 5,  # LOCK-6
) -> str:
    """Build the B6 prompt-injection block for ``agent_profile_id``.

    Args:
        agent_profile_id: The calling agent's registry id (e.g.
            ``vm107.macro_story_tracker``). Recorded in the
            ``EpisodicQuery.requesting_profile`` field for observability.
        query_text: The text the agent will use as the query basis. Service
            will embed it via the configured embedding service if no vector
            was pre-computed.
        episodic_memory_service: Live ``EpisodicMemoryService`` instance.
        top_k: Number of episodes to retrieve. Default 5 (LOCK-6).

    Returns:
        The complete prompt-injection block as a single string. Always
        starts with ``"## Relevant prior episodes"``; never empty.
    """
    result = episodic_memory_service.query(EpisodicQuery(
        query_id=uuid.uuid4(),
        requesting_profile=agent_profile_id,
        requesting_sub_profile=None,
        query_text=query_text,
        query_embedding=None,
        scope={"collection": "macro_episode"},
        top_k=top_k,
        memory_types_requested=["episodic"],
        timestamp=datetime.now(tz=timezone.utc),
    ))

    lines = ["## Relevant prior episodes"]
    if not result.memories_retrieved:
        lines.append("(no relevant prior episodes)")
    else:
        for i, mem in enumerate(result.memories_retrieved, start=1):
            citation = (
                mem.citations[0].citation_ref
                if mem.citations
                else f"[ref:episode:{mem.memory_id}]"
            )
            lines.append(f"{i}. {citation} {mem.text}")
    return "\n".join(lines)
