"""Paths, the Jinja templates and the logger shared by ``app.web.routers.*``."""

import logging
from pathlib import Path

from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"
CHAT_APP_DIR = STATIC_DIR / "chat"
WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
MAX_CHAT_UPLOAD_BYTES = 25 * 1024 * 1024
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def local_demo() -> bool:
    # A notice only; it changes no behaviour.
    import os

    return os.environ.get("OCTRYX_DEMO_NOTICE") == "1"


templates.env.globals["local_demo"] = local_demo
logger = logging.getLogger(__name__)
