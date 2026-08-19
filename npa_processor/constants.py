"""Backward-compatible exports for canonical NPA constants.

The domain layer is the single source of truth.  Existing imports from this
module remain valid while new code should import from ``npa_processor.domain``.
"""

from npa_processor.domain.element_types import TYPE_TO_RUSSIAN

__all__ = ["TYPE_TO_RUSSIAN"]
