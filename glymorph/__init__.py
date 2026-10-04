"""Glymorph: trajectory font variants with selectable length and scaling operations."""

__version__ = "0.2.0"

from .transforms import Options
from .pipeline import generate_variants

__all__ = ['Options', 'generate_variants', '__version__']
