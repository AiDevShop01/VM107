"""
chat_model_call_before extension hook directory.

Agent Zero discovers extension directories by scanning for subdirectories under
extensions/python/. This __init__.py is a marker file that ensures the directory
is recognized as a Python package and detected at agent startup.

The actual router apply extension (_10_model_router_apply.py) is added in Plan 05.
This file must exist BEFORE Plan 05 because Agent Zero scans directories at startup —
if the directory doesn't exist when the container starts, the hook never fires.

Extension files in this directory:
    _10_model_router_apply.py  — (Plan 05) Applies model swap from loop_data.params_temporary
                                  into call_data["model"] + sets fallback chain.

Hook invocation context (from agent.py research):
    - Fires synchronously before LiteLLMChatWrapper.unified_call()
    - Receives: loop_data (LoopData), call_data (mutable dict)
    - call_data["model"] is the LiteLLMChatWrapper instance — replaceable here
    - loop_data.params_temporary["router_decision"] set by before_main_llm_call extension
"""
