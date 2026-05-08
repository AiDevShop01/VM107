"""Strategy override modules. Each module's import side-effect registers its
overrides + hard-reject predicates with the framework.

Plan 05 ships ``model_2_option_1_short.py``. ``Framework()`` boot imports
this package (``from . import strategies``) to trigger the side-effects
before the boot-time hard-reject assertion runs.

When adding a new strategy:
  1. Drop a new YAML at ``VM107/agents/agent0/strategies/<id>.yaml``.
  2. Create a Python module here at ``<id>.py`` with @register_override and
     @register_hard_reject decorators for every YAML hard_reject name.
  3. Add ``from . import <id>  # noqa: F401`` below.
  4. ``Framework()`` boot will validate that every YAML hard_reject name has
     a registered predicate (CF-5 / OQ-7).
"""

from . import model_2_option_1_short  # noqa: F401
