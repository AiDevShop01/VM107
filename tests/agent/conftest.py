"""conftest.py for tests/agent/ — ensures the real ``agent`` module is loaded
into sys.modules BEFORE test_subordinate_invoker_json_extraction can install a
MagicMock stub.

test_subordinate_invoker_json_extraction.py uses:
    sys.modules.setdefault("agent", MagicMock())   # at module-collection time

``setdefault`` is a no-op if the key already exists.  By importing ``agent``
here — in a conftest that pytest processes before collecting individual test
files — we guarantee the real module is in sys.modules first, and the setdefault
call in test_subordinate_invoker becomes a no-op.

This conftest does NOT change the behaviour of test_subordinate_invoker tests:
they import from ``helpers.mentor_subordinate_invoker`` which already has its
own module-level stub setup; what they need is that the stub is in sys.modules
when the helpers module is first imported.  Since conftest.py's import of
``agent`` loads the REAL module, and subsequent ``import agent`` statements in
test bodies get the real one, the subordinate invoker tests are unaffected
because they rely on the already-imported ``helpers.mentor_subordinate_invoker``
module (cached in sys.modules) rather than re-importing agent themselves.
"""
import sys
from pathlib import Path

# Ensure the VM107 root is on sys.path so ``import agent`` resolves correctly.
_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

# Load the real agent module eagerly — this must happen before any test file
# in this directory is collected, which conftest.py guarantees.
if "agent" not in sys.modules:
    import agent  # noqa: F401
