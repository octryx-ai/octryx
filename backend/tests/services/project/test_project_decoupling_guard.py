from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[3] / "app"
ALLOWED_PREFIXES = (APP_ROOT / "web" / "static",)


def test_project_specific_names_do_not_leak_into_core_runtime() -> None:
    leaks = [
        str(path.relative_to(APP_ROOT))
        for path in APP_ROOT.rglob("*.py")
        if not any(prefix in path.parents for prefix in ALLOWED_PREFIXES)
        and "acme-orders" in path.read_text(encoding="utf-8").lower()
    ]
    assert leaks == []
