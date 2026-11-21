"""Shared constants for control-plane runtime configuration."""

from __future__ import annotations

from ...config import get_settings

settings = get_settings()

DEFAULT_OLLAMA_RUNTIME_REQUEST_TIMEOUT_SECONDS = 180.0
DEFAULT_OLLAMA_MAX_TOKENS_PER_REQUEST = 512
