"""Canonical channel plugin implementations."""

from .email_plugin import EmailPlugin
from .matrix_plugin import MatrixPlugin
from .slack_plugin import SlackPlugin
from .teams_plugin import TeamsPlugin
from .telegram import TelegramPlugin

__all__ = [
    "EmailPlugin",
    "MatrixPlugin",
    "SlackPlugin",
    "TeamsPlugin",
    "TelegramPlugin",
]
