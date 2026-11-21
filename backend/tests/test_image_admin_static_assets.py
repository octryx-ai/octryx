"""The image ships the stylesheet the server-rendered admin pages link.

`templates/base.html` (the server-rendered `/admin/*` shell, e.g. `/admin/tools`) links
`/admin/static/chat/admin-design-tokens.css`. The chat frontend build emits it from its one source file, and the
Dockerfile ships that build's output tree; both local dev and the image get it from `npm run build`, so container
images serve those pages styled.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = REPO_ROOT / "frontend" / "chat"
STYLESHEET = "admin-design-tokens.css"
STATIC_MOUNT = "backend/app/web/static/chat"


def _stage(dockerfile: str, name: str) -> str:
    match = re.search(rf"^FROM [^\n]+ AS {re.escape(name)}\n(.*?)(?=^FROM |\Z)", dockerfile, re.M | re.S)
    assert match, f"Dockerfile has no stage {name}"
    return match.group(1)


def test_admin_pages_link_the_stylesheet_from_the_chat_static_mount() -> None:
    base = (REPO_ROOT / "backend" / "app" / "web" / "templates" / "base.html").read_text(encoding="utf-8")
    assert f'href="/admin/static/chat/{STYLESHEET}"' in base


def test_the_frontend_build_emits_the_stylesheet_into_the_static_mount() -> None:
    assert (FRONTEND / "src" / "styles" / "chat" / STYLESHEET).is_file()
    vite_config = (FRONTEND / "vite.config.ts").read_text(encoding="utf-8")
    assert 'outDir: resolve(__dirname, "../../backend/app/web/static/chat")' in vite_config
    assert f'const ADMIN_PAGES_STYLESHEET = "{STYLESHEET}";' in vite_config
    assert 'resolve(__dirname, "src/styles/chat", ADMIN_PAGES_STYLESHEET)' in vite_config
    assert "fileName: ADMIN_PAGES_STYLESHEET" in vite_config
    assert re.search(r"plugins: \[[^\]]*adminPagesStylesheet\(\)", vite_config)


def test_the_image_ships_the_built_static_tree_with_the_stylesheet_source() -> None:
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    build = _stage(dockerfile, "chat-frontend-build")
    assert "COPY frontend/chat/ ./" in build, "the build stage must see src/styles/chat"
    assert "npm run build" in build.split("COPY frontend/chat/ ./", 1)[1]
    runtime = _stage(dockerfile, "runtime-closure")
    assert f"COPY --from=chat-frontend-build /app/{STATIC_MOUNT} ./app/web/static/chat" in runtime

    dockerignore = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "!frontend/chat/**" in dockerignore
    assert not [line for line in dockerignore if line.startswith("frontend/chat/src")]


def test_dev_start_uses_the_build_output_instead_of_a_second_copy() -> None:
    dev_start = (REPO_ROOT / "dev-start.sh").read_text(encoding="utf-8")
    assert "src/styles/chat/admin-design-tokens.css" not in dev_start
    assert f"for built_file in index.html {STYLESHEET}; do" in dev_start
