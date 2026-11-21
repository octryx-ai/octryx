"""Canonical browser automation service package surface."""

from ..persistent_process_runtime import PersistentProcessHandle, spawn_persistent_stdio_process
from .service import BrowserAutomationManager, BrowserAutomationSession, browser_automation_manager

__all__ = [
    "BrowserAutomationManager",
    "BrowserAutomationSession",
    "PersistentProcessHandle",
    "browser_automation_manager",
    "spawn_persistent_stdio_process",
]
