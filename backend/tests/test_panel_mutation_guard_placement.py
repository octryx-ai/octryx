"""The guard placement rule rejects every guard that is not the first boundary and accepts the shape the surface uses."""

from __future__ import annotations

import pytest

from tests.panel_mutation_inventory_support import guard_placement

BAD_SHAPES = {
    "no guard at all": """
        async def handler(request, db):
            return await service_call(db)
    """,
    "guard in dead code after the mutation returns": """
        async def handler(request, db):
            return await service_call(db)
            user = await _require_admin_api(request, db)
    """,
    "guard behind a condition": """
        async def handler(request, db):
            if request.headers.get("x-internal") != "1":
                user = await _require_admin_api(request, db)
            return await service_call(db)
    """,
    "guard inside a nested function that is never called": """
        async def handler(request, db):
            async def _guard():
                return await _require_admin_api(request, db)
            return await service_call(db)
    """,
    "guard after the mutation has already happened": """
        async def handler(request, db):
            created = await service_call(db)
            user = await _require_admin_api(request, db)
            return created
    """,
    "guard swallowed by a try block": """
        async def handler(request, db):
            try:
                user = await _require_admin_api(request, db)
            except Exception:
                user = None
            return await service_call(db)
    """,
    "guard called but never awaited": """
        async def handler(request, db):
            _require_admin_api(request, db)
            return await service_call(db)
    """,
    "principal resolved by hand": """
        async def handler(request, db):
            user_id = _get_user_from_cookie(request)
            return await service_call(db, user_id)
    """,
    "guard reached only after another await": """
        async def handler(request, db):
            settings = await load_settings(db)
            user = await _require_admin_api(request, db)
            return settings
    """,
}


@pytest.mark.parametrize("shape", sorted(BAD_SHAPES), ids=lambda name: name.replace(" ", "_"))
def test_the_placement_rule_rejects_a_guard_that_is_not_the_first_boundary(shape):
    placement = guard_placement(BAD_SHAPES[shape])
    assert not placement.ok, f"the gate would have accepted a handler with the guard {shape}"
    assert placement.problem


@pytest.mark.parametrize(
    "source",
    [
        """
        async def handler(request, db):
            user = await _require_admin_api(request, db)
            return await service_call(db, user)
        """,
        """
        @router.post("/chat/api/panel/things")
        async def handler(request, db):
            \"\"\"Docstring first is fine.\"\"\"
            await _require_api_user(request, db)
            return await service_call(db)
        """,
        """
        async def handler(request, db):
            user = await _require_admin_permission_api(request, db, resource="users", action="write")
            return await service_call(db, user)
        """,
    ],
    ids=["assigned", "decorated_with_docstring", "keyword_arguments"],
)
def test_the_placement_rule_accepts_the_shape_the_surface_uses(source):
    assert guard_placement(source).ok
