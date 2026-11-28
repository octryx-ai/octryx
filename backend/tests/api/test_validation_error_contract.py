"""A request a Pydantic validator refuses answers 422 with a JSON body, never 500."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, field_validator

from app.api.routes.error_contracts import validation_exception_handler
from app.api.routes.knowledge.knowledge_source_settings import router as settings_router
from app.db import get_db
from app.services.auth import get_current_user
from tests.knowledge_evidence_seed_support import seed_workspace


class _Named(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A name is required.")
        return value


def _app() -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    return app


async def test_any_route_whose_validator_raises_value_error_answers_422_json() -> None:
    app = _app()

    @app.post("/api/v1/things")
    async def create(body: _Named) -> dict:
        return {"name": body.name}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://contract.test") as client:
        answer = await client.post("/api/v1/things", json={"name": "  "})

    assert answer.status_code == 422
    payload = answer.json()
    [error] = payload["validation_errors"]
    assert error["loc"] == ["body", "name"] and "A name is required." in error["msg"]
    assert error["ctx"]["error"] == "A name is required."


@pytest.mark.parametrize("reason", ["", "   "])
async def test_a_blank_source_acl_reason_is_422_with_the_message_not_500(db, reason: str, auth_user) -> None:
    app = _app()
    app.include_router(settings_router)

    async def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: auth_user
    workspace_id = await seed_workspace(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://knowledge.test") as client:
        answer = await client.put(f"/api/v1/workspaces/{workspace_id}/knowledge/source-acl",
                                  json={"enforce": True, "reason": reason})

    assert answer.status_code == 422
    payload = answer.json()
    assert payload["detail"] == "Validation failed" and payload["status_code"] == 422
    [error] = payload["validation_errors"]
    assert error["loc"] == ["body", "reason"] and "A reason is required." in error["msg"]
