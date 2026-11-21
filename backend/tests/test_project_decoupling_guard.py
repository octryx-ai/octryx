from pathlib import Path


def test_project_specific_names_do_not_leak_into_core_runtime() -> None:
    app_root = Path("backend/app")
    allowed_paths = {
        Path("backend/app/bootstrap.py"),
        Path("backend/app/tools/knowledge_impl/_knowledge_gold_portfolio.py"),
    }
    allowed_prefixes = {
        Path("backend/app/services/sample_workspace_bootstrap"),
        Path("backend/app/web/static"),
    }
    leaks: list[str] = []
    for path in app_root.rglob("*.py"):
        if path in allowed_paths:
            continue
        if any(path == prefix or prefix in path.parents for prefix in allowed_prefixes):
            continue
        content = path.read_text(encoding="utf-8")
        lowered = content.lower()
        if "acme-orders" in lowered:
            leaks.append(str(path))

    assert leaks == []
