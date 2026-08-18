"""Фасад для обратной совместимости. Реэкспортирует все утилиты из подмодулей."""

from npa_processor.processing.text_utils import *
from npa_processor.processing.html_utils import *
from npa_processor.processing.ai_utils import *
from npa_processor.processing.json_utils import *
from npa_processor.processing.tree_utils import *
from npa_processor.processing.ui_utils import *

# WARNING: star-imports from submodules may cause circular import risks if submodules
# start importing from revision_utils. Keep this facade read-only or convert to explicit
# re-exports when refactoring.
