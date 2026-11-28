from __future__ import annotations

from pathlib import Path

import pytest

from tests.guards._comment_style import Counts, comment_style_counts

DOCSTRING = '    """One line."""\n'


def _scan(root: Path, files: dict[str, str]) -> dict[str, Counts]:
    for relative, source in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    return comment_style_counts(root, [root / relative for relative in files if relative.endswith(".py")])


@pytest.mark.parametrize("files", [
    {"backend/app/api/items.py": '@items_router.get("/items")\nasync def list_items():\n' + DOCSTRING},
    {"backend/app/main.py": '@app.websocket("/ws")\nasync def socket():\n' + DOCSTRING},
    {"backend/app/services/mcp_planted.py": (
        "def register(server):\n    @server.tool(description='Read.')\n    async def read_item():\n    " + DOCSTRING
    )},
    {
        "backend/app/tools/registry_impl/_registry_toolset_planted.py": (
            "from app.tools.planted import PlantedTool\n\nTOOL_CLASSES_PLANTED = [PlantedTool]\n"
        ),
        "backend/app/tools/planted.py": (
            "class PlantedTool:\n" + DOCSTRING + "    name = 'planted'\n"
            "    async def execute(self, params, context):\n    " + DOCSTRING
        ),
    },
    {
        "backend/app/services/planted/__init__.py": "from .engine import Engine, run\n",
        "backend/app/services/planted/engine.py": (
            "def run():\n" + DOCSTRING + "class Engine:\n" + DOCSTRING + "    def start(self):\n    " + DOCSTRING
        ),
    },
    {
        "backend/app/services/planted/__init__.py": "__all__ = ['run']\n",
        "backend/app/services/planted/runner.py": "def run():\n" + DOCSTRING,
    },
    {"backend/app/services/planted/cli.py": "def main():\n" + DOCSTRING + "\nif __name__ == '__main__':\n    main()\n"},
    {
        "clients/octryx-claude/octryx_claude/pet/__main__.py": "import sys\n\nfrom .cli import main\n\nsys.exit(main())\n",
        "clients/octryx-claude/octryx_claude/pet/cli.py": "def main():\n" + DOCSTRING,
    },
    {
        "clients/octryx-claude/pyproject.toml": '[project.scripts]\noctryx = "octryx_claude.entry:main"\n',
        "clients/octryx-claude/octryx_claude/entry.py": "def main():\n" + DOCSTRING,
    },
])
def test_mutation_short_docstring_on_a_public_interface_passes(tmp_path: Path, files: dict[str, str]) -> None:
    assert _scan(tmp_path, files) == {}


@pytest.mark.parametrize(("files", "planted"), [
    ({"backend/app/api/items.py": (
        '@router.get("/items")\nasync def list_items():\n' + DOCSTRING + "    def helper():\n    " + DOCSTRING
    )}, "backend/app/api/items.py"),
    ({"backend/app/services/mcp_planted.py": "def register(server):\n" + DOCSTRING}, "backend/app/services/mcp_planted.py"),
    ({
        "backend/app/services/planted/__init__.py": "from .engine import Engine\n",
        "backend/app/services/planted/engine.py": "class Engine:\n    def _step(self):\n    " + DOCSTRING,
    }, "backend/app/services/planted/engine.py"),
    ({
        "backend/app/services/planted/__init__.py": "from .engine import Engine\n",
        "backend/app/services/planted/engine.py": "class Engine:\n    pass\n\n\ndef run():\n" + DOCSTRING,
    }, "backend/app/services/planted/engine.py"),
    ({"backend/app/services/planted/cli.py": "def main():\n" + DOCSTRING}, "backend/app/services/planted/cli.py"),
    ({"backend/tests/api/test_routes.py": '@app.get("/x")\ndef read():\n' + DOCSTRING}, "backend/tests/api/test_routes.py"),
])
def test_mutation_docstring_beside_a_public_interface_is_reported(
    tmp_path: Path, files: dict[str, str], planted: str,
) -> None:
    assert _scan(tmp_path, files) == {planted: (1, 0, 0, 0, 0)}
