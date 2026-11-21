from __future__ import annotations

import logging

from jinja2 import Environment, StrictUndefined

logger = logging.getLogger(__name__)

ALLOWED_CHANNEL_TYPES = {"email", "slack", "teams"}
DELIVERY_RETRY_DELAYS_SECONDS = [5, 30, 120]
TEMPLATE_ENV = Environment(autoescape=False, trim_blocks=True, lstrip_blocks=True, undefined=StrictUndefined)
