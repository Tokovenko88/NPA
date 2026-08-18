"""Shim module for backward compatibility. Imports from html_parser."""
from npa_processor.core.html_parser import NpaToJsonGenerator

__all__ = ['NpaToJsonGenerator']
