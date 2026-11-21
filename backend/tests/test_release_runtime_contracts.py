"""Current private runtime markers preserve the public execution and error contracts."""

from app.exceptions.contract import get_error_contract, with_error_contract
from app.services.python_runtime_entrypoint import PythonWorker


def test_error_metadata_survives_without_public_attributes():
    error = with_error_contract(ValueError("invalid input"), error_code="invalid_input", retryable=False)
    del error.error_code
    del error.retryable
    contract = get_error_contract(error)
    assert contract.error_code == "invalid_input" and contract.retryable is False


def test_interactive_python_uses_current_namespace_and_preserves_variables():
    worker = PythonWorker()
    assert worker._exec_code("__name__")["result"] == "'__octryx_python_runtime__'"
    assert worker._exec_code("count = 4")["stderr"] == ""
    assert worker._exec_code("count + 1")["result"] == "5"
