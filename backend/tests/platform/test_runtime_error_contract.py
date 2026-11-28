from __future__ import annotations

import pytest

from app.exceptions.contract import build_error_response, get_error_contract, with_error_contract


@pytest.mark.parametrize(
    ("error_code", "message"),
    [
        ("browser_invalid_argument", "url is required"),
        ("python_invalid_argument", "code is required"),
    ],
)
def test_build_error_response_serializes_runtime_error_contract(error_code: str, message: str) -> None:
    exc = with_error_contract(ValueError(message), error_code=error_code, retryable=False)

    payload = build_error_response(exc, request_id="request-1")

    assert payload == {
        "message": message,
        "error_code": error_code,
        "retryable": False,
        "request_id": "request-1",
    }


def test_get_error_contract_defaults_to_internal_error_for_plain_payload() -> None:
    contract = get_error_contract({"message": "boom"})

    assert contract.error_code == "internal_error"
    assert contract.retryable is False
