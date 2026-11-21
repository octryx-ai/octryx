"""Persistent interactive Python worker entrypoint."""

from __future__ import annotations

import ast
import asyncio
import contextlib
import io
import json
import traceback
from typing import Any

from app.exceptions.contract import build_error_response, with_error_contract


class PythonWorker:
    def __init__(self) -> None:
        self.globals: dict[str, Any] = {"__name__": "__octryx_python_runtime__"}

    def _exec_code(self, code: str) -> dict[str, Any]:
        buffer_out = io.StringIO()
        buffer_err = io.StringIO()
        result_repr: str | None = None
        with contextlib.redirect_stdout(buffer_out), contextlib.redirect_stderr(buffer_err):
            try:
                module = ast.parse(code, mode="exec")
                if module.body and isinstance(module.body[-1], ast.Expr):
                    expr = module.body.pop()
                    exec(compile(module, "<octryx-python>", "exec"), self.globals, self.globals)
                    code = compile(ast.Expression(expr.value), "<octryx-python>", "eval")
                    value = eval(code, self.globals, self.globals)
                    result_repr = repr(value)
                else:
                    exec(compile(module, "<octryx-python>", "exec"), self.globals, self.globals)
            except Exception:
                buffer_err.write(traceback.format_exc())
        return {
            "stdout": buffer_out.getvalue(),
            "stderr": buffer_err.getvalue(),
            "result": result_repr,
        }

    def _list_variables(self) -> dict[str, Any]:
        variables: list[dict[str, Any]] = []
        for name, value in sorted(self.globals.items(), key=lambda item: item[0]):
            if name.startswith("__"):
                continue
            variables.append(
                {
                    "name": name,
                    "type": type(value).__name__,
                    "repr": repr(value)[:240],
                }
            )
        return {"variable_count": len(variables), "variables": variables}

    async def handle(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if action == "exec_code":
            code = str(params.get("code") or "")
            if not code.strip():
                raise with_error_contract(
                    ValueError("code is required"),
                    error_code="python_invalid_argument",
                    retryable=False,
                )
            return self._exec_code(code)
        if action == "list_variables":
            return self._list_variables()
        if action == "close":
            return {"closed": True}
        raise with_error_contract(
            ValueError(f"Unsupported python action: {action}"),
            error_code="python_unsupported_action",
            retryable=False,
        )


async def _run() -> None:
    worker = PythonWorker()
    loop = asyncio.get_running_loop()
    while True:
        raw_line = await loop.run_in_executor(None, input)
        if not raw_line:
            break
        payload: dict[str, Any] | None = None
        try:
            payload = json.loads(raw_line)
            request_id = str(payload.get("id") or "")
            action = str(payload.get("action") or "").strip()
            params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
            result = await worker.handle(action, params)
            response = {"id": request_id, "ok": True, "result": result}
        except EOFError:
            break
        except Exception as exc:  # pragma: no cover - exercised through service layer
            request_id = str(payload.get("id") or "") if payload else ""
            response = {
                "id": request_id,
                "ok": False,
                "error": build_error_response(exc, request_id=request_id or None),
            }
        print(json.dumps(response, ensure_ascii=False), flush=True)
        if response.get("ok") and action == "close":
            break


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
