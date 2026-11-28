from __future__ import annotations

from tests.guards._dynamic_loaders import COMPUTED_DUNDER_IMPORT, detected_sites
from tests.guards._import_graph import index_sources, reachable

_GENERATED_SCRIPT_SOURCE = "app/tools/office_impl/_office_excel_script_template.py"


def _reached(sources: dict[str, str]) -> set[str]:
    index = index_sources({"app/__init__.py": "", **sources})
    return reachable(index, ["app.main"], {})


def test_literal_dunder_import_is_an_edge() -> None:
    sources = {"app/main.py": "loaded = __import__('app.lazy')\n", "app/lazy.py": ""}
    assert "app.lazy" in _reached(sources)
    assert detected_sites(index_sources({"app/__init__.py": "", **sources})) == set()


def test_computed_dunder_import_is_a_dynamic_loader() -> None:
    index = index_sources({"app/__init__.py": "", "app/main.py": "def load(name):\n    return __import__(name)\n"})
    assert detected_sites(index) == {("app.main", COMPUTED_DUNDER_IMPORT)}


def test_import_text_in_an_ordinary_string_is_not_an_edge() -> None:
    sources = {"app/main.py": "HINT = 'run:\\nfrom app import dead\\n'\n", "app/dead.py": ""}
    assert "app.dead" not in _reached(sources)


def test_import_text_in_a_generated_script_source_is_an_edge() -> None:
    sources = {
        "app/main.py": "from app.tools.office_impl import _office_excel_script_template\n",
        "app/tools/__init__.py": "",
        "app/tools/office_impl/__init__.py": "",
        _GENERATED_SCRIPT_SOURCE: "def render():\n    return '\\nfrom app.services import engine\\n'\n",
        "app/services/__init__.py": "",
        "app/services/engine.py": "",
    }
    assert "app.services.engine" in _reached(sources)


def test_import_prose_in_a_generated_script_source_docstring_is_not_an_edge() -> None:
    sources = {
        "app/main.py": "from app.tools.office_impl import _office_excel_script_template\n",
        "app/tools/__init__.py": "",
        "app/tools/office_impl/__init__.py": "",
        _GENERATED_SCRIPT_SOURCE: '"""Example:\n\nfrom app.services import engine\n"""\n\n'
                                  "def render():\n    \"\"\"Use like:\n    import app.services.engine\n    \"\"\"\n"
                                  "    return 'print(1)'\n",
        "app/services/__init__.py": "",
        "app/services/engine.py": "",
    }
    assert "app.services.engine" not in _reached(sources)


def test_literal_dunder_import_from_lists_and_levels_are_edges() -> None:
    for call in ("__import__('app', fromlist=['lazy'])", "__import__('app', None, None, ('lazy',))",
                 "__import__('lazy', globals(), level=1)", "__import__('lazy', globals(), locals(), [], 1)",
                 "__import__('', globals(), locals(), ['lazy'], 1)"):
        sources = {"app/main.py": f"loaded = {call}\n", "app/lazy.py": ""}
        assert "app.lazy" in _reached(sources), call
        assert detected_sites(index_sources({"app/__init__.py": "", **sources})) == set(), call


def test_computed_dunder_import_arguments_are_dynamic_loaders() -> None:
    for call in ("__import__('app', fromlist=names)", "__import__('app', None, None, [name])",
                 "__import__('lazy', globals(), level=depth)", "__import__('app', None, None, NAMES, 0)"):
        index = index_sources({"app/__init__.py": "", "app/main.py": f"def load(names, name, depth):\n"
                                                                     f"    return {call}\n"})
        assert detected_sites(index) == {("app.main", COMPUTED_DUNDER_IMPORT)}, call
