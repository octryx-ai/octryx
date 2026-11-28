import pytest

import app.tools.definitions as tool_definitions_module
from app.tools.definitions.admin import get_admin_definitions


def test_get_all_definitions_rejects_duplicate_names(monkeypatch: pytest.MonkeyPatch) -> None:
    admin_definitions = get_admin_definitions()
    duplicate_name = next(iter(admin_definitions))

    monkeypatch.setattr(
        tool_definitions_module,
        "DEFINITION_GETTERS",
        (lambda: admin_definitions, lambda: {duplicate_name: admin_definitions[duplicate_name]}),
    )

    with pytest.raises(ValueError, match=f"Duplicate tool definition: {duplicate_name}"):
        tool_definitions_module.get_all_definitions()
