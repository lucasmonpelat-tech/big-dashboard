"""Canonical schemas + validators para dashboard v2."""
from .schemas import SCHEMA_VERSION
from . import validators

__all__ = ["SCHEMA_VERSION", "validators"]
