import asyncio
from helpers.extension import Extension
from agent import LoopData
from helpers import dirty_json, errors, log, plugins

# Direct import - this extension lives inside the memory plugin
from plugins._memory.helpers.memory import Memory
from plugins._memory.tools.memory_load import DEFAULT_THRESHOLD as DEFAULT_MEMORY_THRESHOLD


DATA_NAME_TASK = "_recall_memories_task"
DATA_NAME_ITER = "_recall_memories_iter"
SEARCH_TIMEOUT = 30


class RecallMemories(Extension):

    # INTERVAL = 3
    # HISTORY = 10000
    # MEMORIES_MAX_SEARCH = 12
    # SOLUTIONS_MAX_SEARCH = 8
    # MEMORIES_MAX_RESULT = 5
    # SOLUTIONS_MAX_RESULT = 3
    # THRESHOLD = DEFAULT_MEMORY_THRESHOLD

    async def execute(self, loop_data: LoopData = LoopData(), **kwargs):
        if not self.agent:
            return

        set = plugins.get_plugin_config("_memory", self.agent)
        if not set:
            return None

        # turned off in settings?
        if not set["memory_recall_enabled"]:
            return None

        # every X iterations (or the first one) recall memories
        if loop_data.iteration % set["memory_recall_interval"] == 0:

            # show util message right away
            log_item = self.agent.context.log.log(
                type="util",
                heading="Searching memories...",
            )

            task = asyncio.create_task(
                asyncio.wait_for(
                    self.search_memories(loop_data=loop_data, log_item=log_item, **kwargs),
                    timeout=SEARCH_TIMEOUT,
                )
            )
        else:
            task = None

        # set to agent to be able to wait for it
        self.agent.set_data(DATA_NAME_TASK, task)
        self.agent.set_data(DATA_NAME_ITER, loop_data.iteration)

    async def search_memories(self, log_item: log.LogItem, loop_data: LoopData, **kwargs):
        if not self.agent:
            return

        # cleanup
        extras = loop_data.extras_persistent
        if "memories" in extras:
            del extras["memories"]
        if "solutions" in extras:
            del extras["solutions"]


        set = plugins.get_plugin_config("_memory", self.agent)
        if not set:
            return None
        # try:

        # get system message and chat history for util llm
        system = self.agent.read_prompt("memory.memories_query.sys.md")

        # # log query streamed by LLM
        # async def log_callback(content):
        #     log_item.stream(query=content)

        # call util llm to summarize conversation
        user_instruction = (
            loop_data.user_message.output_text() if loop_data.user_message else "None"
        )
        history = self.agent.history.output_text()[-set["memory_recall_history_len"]:]
        message = self.agent.read_prompt(
            "memory.memories_query.msg.md", history=history, message=user_instruction
        )

        # if query preparation by AI is enabled
        if set["memory_recall_query_prep"]:
            try:
                # call util llm to generate search query from the conversation
                query = await self.agent.call_utility_model(
                    system=system,
                    message=message,
                    # callback=log_callback,
                )
                query = query.strip()
                log_item.update(query=query) # no need for streaming here
            except Exception as e:
                err = errors.format_error(e)
                self.agent.context.log.log(
                    type="warning", heading="Recall memories extension error:", content=err
                )
                query = ""

            # no query, no search
            if not query:
                log_item.update(
                    heading="Failed to generate memory query",
                )
                return
        
        # otherwise use the message and history as query
        else:
            query = user_instruction + "\n\n" + history

        # if there is no query (or just dash by the LLM), do not continue
        if not query or len(query) <= 3:
            log_item.update(
                query="No relevant memory query generated, skipping search",
            )
            return

        # get memory database
        db = await Memory.get(self.agent)

        # search for general memories/fragments and solutions concurrently — independent
        # queries (different areas, same db) fanned out via asyncio.gather; both remain lists.
        memories, solutions = await asyncio.gather(
            db.search_similarity_threshold(
                query=query,
                limit=set["memory_recall_memories_max_search"],
                threshold=set["memory_recall_similarity_threshold"],
                filter=f"area == '{Memory.Area.MAIN.value}' or area == '{Memory.Area.FRAGMENTS.value}'",  # exclude solutions
            ),
            db.search_similarity_threshold(
                query=query,
                limit=set["memory_recall_solutions_max_search"],
                threshold=set["memory_recall_similarity_threshold"],
                filter=f"area == '{Memory.Area.SOLUTIONS.value}'",  # solutions only
            ),
        )

        if not memories and not solutions:
            # Empty results are ambiguous: a genuinely-empty corpus vs a Qdrant outage
            # (D3-01/03). Read the fresh health bus (freshened at search time by
            # qdrant_backend.search, D3-02) to distinguish them. WR-04 / T-135-01: the
            # degraded line names the failure CLASS, never a host:port.
            from emitters.source_health_registry import SourceHealthKey, SourceHealthRegistry

            # Context-scope the health read by this agent's immutable context id (135-06),
            # with a bare-key fallback (C floor): read qdrant:{ctxid}/embedding:{ctxid} first,
            # then fall back to the bare "qdrant"/"embedding" record so a key miss for a real
            # ctxid degrades to today's working single-context signal, never plain-empty.
            ctxid = getattr(getattr(self.agent, "context", None), "id", "") or ""
            snap = SourceHealthRegistry.get_shared_instance().snapshot()
            qh = (snap.get(SourceHealthKey("qdrant", ctxid).key) if ctxid else None) or snap.get("qdrant")
            eh = (snap.get(SourceHealthKey("embedding", ctxid).key) if ctxid else None) or snap.get("embedding")

            # Name the REAL failing subsystem (WR-01). T-135-01: name the failure CLASS/
            # subsystem only — never a host:port.
            if eh is not None and eh.available is False:
                log_item.update(
                    heading="Memory recall DEGRADED (embedding service unavailable)",
                    content=(
                        "Long-term memory is currently unavailable (embedding service "
                        "unavailable); recall is impaired, not empty — do not claim you have "
                        "no relevant memories. Proceed cautiously and note that memory could "
                        "not be consulted."
                    ),
                )
            elif qh is not None and qh.available is False:
                # D-05 (P7): classify the EXISTING failure_reason so a swallowed code
                # bug (the 2026-08-12 qdrant_host NameError, surfaced by D-04's init
                # report) reads as an honest "internal error" rather than the
                # misleading "vector store unreachable". code-class = a bug in our
                # code; anything else (connect-class or unknown) stays the
                # conservative "unreachable" so an outage is never silently downgraded
                # to plain-empty. T-135-01: name the CLASS only — never a host:port.
                _CODE_CLASS = {
                    "NameError",
                    "AttributeError",
                    "TypeError",
                    "KeyError",
                    "ImportError",
                    "ModuleNotFoundError",
                    "UnboundLocalError",
                }
                if (qh.failure_reason or "") in _CODE_CLASS:
                    log_item.update(
                        heading="Memory recall DEGRADED (internal error)",
                        content=(
                            "Long-term memory is currently unavailable (qdrant recall hit "
                            "an internal error); recall is impaired, not empty — do not "
                            "claim you have no relevant memories. Proceed cautiously and "
                            "note that memory could not be consulted."
                        ),
                    )
                else:
                    log_item.update(
                        heading="Memory recall DEGRADED (vector store unreachable)",
                        content=(
                            "Long-term memory is currently unavailable (qdrant vector "
                            "store unreachable); recall is impaired, not empty — do not "
                            "claim you have no relevant memories. Proceed cautiously and "
                            "note that memory could not be consulted."
                        ),
                    )
            else:
                log_item.update(
                    heading="No memories or solutions found",
                )
            return

        # if post filtering is enabled
        if set["memory_recall_post_filter"]:
            # assemble an enumerated dict of memories and solutions for AI validation
            mems_list = {i: memory.page_content for i, memory in enumerate(memories + solutions)}

            # call AI to validate the memories
            try:
                filter = await self.agent.call_utility_model(
                    system=self.agent.read_prompt("memory.memories_filter.sys.md"),
                    message=self.agent.read_prompt(
                        "memory.memories_filter.msg.md",
                        memories=mems_list,
                        history=history,
                        message=user_instruction,
                    ),
                )
                filter_inds = dirty_json.try_parse(filter)

                # filter memories and solutions based on filter_inds
                filtered_memories = []
                filtered_solutions = []
                mem_len = len(memories)

                # process each index in filter_inds
                # make sure filter_inds is a list and contains valid integers
                if isinstance(filter_inds, list):
                    for idx in filter_inds:
                        if isinstance(idx, int):
                            if idx < mem_len:
                                # this is a memory
                                filtered_memories.append(memories[idx])
                            else:
                                # this is a solution, adjust index
                                sol_idx = idx - mem_len
                                if sol_idx < len(solutions):
                                    filtered_solutions.append(solutions[sol_idx])

                # replace original lists with filtered ones
                memories = filtered_memories
                solutions = filtered_solutions

            except Exception as e:
                err = errors.format_error(e)
                self.agent.context.log.log(
                    type="warning", heading="Failed to filter relevant memories", content=err
                )
                filter_inds = []


        # limit the number of memories and solutions
        memories = memories[: set["memory_recall_memories_max_result"]]
        solutions = solutions[: set["memory_recall_solutions_max_result"]]

        # log the search result
        log_item.update(
            heading=f"{len(memories)} memories and {len(solutions)} relevant solutions found",
        )

        memories_txt = "\n\n".join([mem.page_content for mem in memories]) if memories else ""
        solutions_txt = "\n\n".join([sol.page_content for sol in solutions]) if solutions else ""

        # log the full results
        if memories_txt:
            log_item.update(memories=memories_txt)
        if solutions_txt:
            log_item.update(solutions=solutions_txt)

        # place to prompt
        if memories_txt:
            extras["memories"] = self.agent.parse_prompt(
                "agent.system.memories.md", memories=memories_txt
            )
        if solutions_txt:
            extras["solutions"] = self.agent.parse_prompt(
                "agent.system.solutions.md", solutions=solutions_txt
            )
