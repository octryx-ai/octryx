"""The app.services root layout: no admin or private helper modules at the root, admin modules in their package."""

from __future__ import annotations

from tests.package_layout_support import _repo_root


def test_services_root_contains_no_admin_modules() -> None:
    root = _repo_root() / "app" / "services"
    forbidden = sorted(path.name for path in root.glob("admin*.py"))
    forbidden.extend(path.name for path in root.glob("_admin*.py"))
    forbidden.sort()
    assert forbidden == [], f"admin modules belong in app.services.admin, not the services root: {forbidden}"


def test_admin_service_package_contains_only_canonical_modules() -> None:
    root = _repo_root() / "app" / "services" / "admin"
    forbidden = sorted(
        path.name
        for path in root.glob("*.py")
        if path.name != "__init__.py" and not path.name.startswith("admin_") and not path.name.startswith("_admin_")
    )
    assert forbidden == [], (
        "admin service package must keep public modules in admin_* files and private helpers in _admin_* files: "
        f"{forbidden}"
    )


def test_services_root_contains_only_public_facades_and_runtime_utilities() -> None:
    """Keep private service helper families out of app.services root."""

    root = _repo_root() / "app" / "services"

    for path in root.glob("*.py"):
        if path.name == "__init__.py":
            continue
        if path.name.startswith("_"):
            raise AssertionError(
                f"{path.as_posix()} should live in a service helper package instead of app.services root."
            )
        if path.name.startswith("code_intelligence_"):
            raise AssertionError(
                f"{path.as_posix()} should live in app.services.code_intelligence instead of app.services root."
            )
        if path.name.startswith("tool_config_") and path.name != "tool_config_service.py":
            raise AssertionError(
                f"{path.as_posix()} should live in app.services.tool_config instead of app.services root."
            )
