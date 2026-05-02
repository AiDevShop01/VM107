"""One-shot inspection — Phase 43.1 Plan 01.

Determines whether `call_data["model"].model_name = decision.primary` is safe
(direct mutation) OR whether Plan 02's _20_router_decide.py must instantiate a
new LiteLLMChatWrapper instead.

Run from VM107 root:
    cd /a0 && python scripts/inspect_litellm_wrapper.py
"""
import inspect, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import LiteLLMChatWrapper

# 1. Is model_name a property (with setter side-effects) or a plain attribute?
attr = inspect.getattr_static(LiteLLMChatWrapper, "model_name", None)
if isinstance(attr, property):
    print("RESULT: model_name is a property — Plan 02 MUST instantiate a new LiteLLMChatWrapper, not mutate")
    print(f"  fset: {attr.fset!r}")
else:
    print(f"RESULT: model_name is NOT a class-level property (got {type(attr)!r})")
    # 2. Verify it's set as instance attr in __init__
    src = inspect.getsource(LiteLLMChatWrapper.__init__)
    if "self.model_name" in src:
        print("  SAFE: __init__ sets self.model_name as plain instance attr — direct mutation is OK")
    else:
        print("  UNCLEAR: __init__ does not visibly set self.model_name — manual review needed")

# 3. Print __init__ signature so Plan 02 knows constructor kwargs if new instantiation needed
print("\nLiteLLMChatWrapper.__init__ signature:")
print(f"  {inspect.signature(LiteLLMChatWrapper.__init__)}")
