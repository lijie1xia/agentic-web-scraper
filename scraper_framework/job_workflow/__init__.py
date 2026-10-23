"""Local-only job workflow; importing this package performs no network I/O."""

from .repository import Repository

__all__ = ['Repository']
