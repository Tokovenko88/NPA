"""Фасад для обратной совместимости. Реэкспортирует публичные утилиты из подмодулей.

Star imports are used here intentionally: the submodules have no formal
``__all__``, and the three consumer modules (``element_finder``,
``revision_builder``, ``change_applier``) depend on receiving the full
set of public names from every submodule via ``from ...revision_utils import *``.

To keep star imports from pulling in private/internal symbols (those starting
with ``_``) and module-level imports (like ``re``, ``os``, ``json``), each
submodule below only exposes names whose ``__module__`` matches itself.
"""

from npa_processor.processing.text_utils import *
from npa_processor.processing.html_utils import *
from npa_processor.processing.ai_utils import *
from npa_processor.processing.json_utils import *
from npa_processor.processing.tree_utils import *
from npa_processor.processing.ui_utils import *
