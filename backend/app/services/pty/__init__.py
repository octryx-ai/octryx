"""Canonical package surface for PTY session management."""

from .service import _IS_UNIX, PTYManager, PTYSession, pty_manager

__all__ = ["PTYManager", "PTYSession", "_IS_UNIX", "pty_manager"]
