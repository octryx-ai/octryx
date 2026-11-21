from app.tools.runtime_impl import _runtime_cli_helpers as helpers


def test_code_intelligence_provenance_collects_runtime_backend_metadata():
    payload = {
        "repository": {
            "effective_backends": {
                "definitions": "ripgrep",
                "references": "ast-grep",
            }
        },
        "engines": {
            "outline": "tree-sitter",
            "search": "ripgrep",
        },
        "search_backend": "ripgrep",
        "structure_backend": "tree-sitter",
        "graph_backend": "networkx",
        "definitions": [{"backend": "ripgrep"}, {"backend": "ast-grep"}, {"backend": ""}],
        "references": [{"backend": "ast-grep"}, {"backend": "ripgrep"}],
        "callers": [{"backend": "tree-sitter"}],
        "outline": [{"backend": "tree-sitter"}, {"backend": "tree-sitter"}],
    }

    assert helpers._code_intelligence_provenance(payload) == {
        "repository_effective_backends": {
            "definitions": "ripgrep",
            "references": "ast-grep",
        },
        "snapshot_engines": {
            "outline": "tree-sitter",
            "search": "ripgrep",
        },
        "search_backend": "ripgrep",
        "structure_backend": "tree-sitter",
        "graph_backend": "networkx",
        "definition_backends": ["ast-grep", "ripgrep"],
        "reference_backends": ["ast-grep", "ripgrep"],
        "caller_backends": ["tree-sitter"],
        "outline_backends": ["tree-sitter"],
    }


def test_with_code_intelligence_provenance_uses_runtime_cli_patch_point(monkeypatch):
    monkeypatch.setattr(
        helpers,
        "_code_intelligence_provenance",
        lambda payload: {"patched": payload.get("search_backend") or "missing"},
    )

    assert helpers._with_code_intelligence_provenance({"search_backend": "patched-search"}) == {
        "search_backend": "patched-search",
        "provenance": {"patched": "patched-search"},
    }
