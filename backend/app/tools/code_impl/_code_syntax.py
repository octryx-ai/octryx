"""Syntax checking tool for workspace files."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from app.services.execution_runtime.build_guard_rules import SERVER_BUILD_MESSAGE, SERVER_BUILD_NOT_ALLOWED
from app.tools.context import ToolContext

from ...services.process_output_redaction import redact_process_output
from ._code_common import _resolve_workspace_path

_SYNTAX_CHECKERS: dict[str, list[str]] = {
    ".py": ["python3", "-m", "py_compile"],
    ".sh": ["bash", "-n"],
    ".json": ["python3", "-m", "json.tool"],
    ".yaml": ["python3", "-c", "import sys,yaml; yaml.safe_load(open(sys.argv[1]))", "__FILE__"],
    ".yml": ["python3", "-c", "import sys,yaml; yaml.safe_load(open(sys.argv[1]))", "__FILE__"],
    ".go": ["go", "vet"],
    ".java": ["javac", "-proc:none"],
    ".ts": ["node", "--check"],
    ".tsx": ["node", "--check"],
    ".js": ["node", "--check"],
    ".jsx": ["node", "--check"],
}

# Checkers that build rather than parse; the others parse only and run from the API's own directory.
_SERVER_REFUSED_CHECKERS = frozenset({"go"})

_EXT_TO_LANG = {
    ".py": "python",
    ".sh": "shell",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".go": "go",
    ".java": "java",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
}


class CheckFileSyntaxTool:
    name = "check_file_syntax"
    description = (
        "Check the syntax of a file using language-specific tools (py_compile, bash -n, node --check, etc.). "
        "Supported: .py, .sh, .json, .yaml, .yml, .go, .java, .ts, .tsx, .js, .jsx. "
        "Returns valid=true/false plus any errors with line numbers."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        raw_path = str(params.get("path") or params.get("file_path") or "").strip()
        if not raw_path:
            return {"error": "path is required"}

        file_path = _resolve_workspace_path(raw_path, context.workspace_root)
        if not file_path.exists():
            return {"error": f"File not found: {file_path}"}

        ext = file_path.suffix.lower()
        language = str(params.get("language") or _EXT_TO_LANG.get(ext) or "unknown")

        checker = _SYNTAX_CHECKERS.get(ext)
        if not checker:
            return {
                "path": str(file_path),
                "language": language,
                "valid": None,
                "message": f"No syntax checker for extension '{ext}'",
            }

        if checker[0] in _SERVER_REFUSED_CHECKERS:
            # ``go vet`` builds the file's package (module resolution, cgo); not on the server.
            return {"path": str(file_path), "language": language, "valid": None, "message": SERVER_BUILD_MESSAGE,
                    "error_code": SERVER_BUILD_NOT_ALLOWED}

        cmd = [c if c != "__FILE__" else str(file_path) for c in checker]
        if cmd[-1] != str(file_path) and "__FILE__" not in checker:
            cmd.append(str(file_path))

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        except TimeoutError:
            return {
                "path": str(file_path),
                "language": language,
                "valid": False,
                "errors": [{"message": "Syntax check timed out"}],
            }
        except FileNotFoundError:
            # The OS error text is not kept; the checker name comes from the fixed table above.
            return {
                "path": str(file_path),
                "language": language,
                "valid": None,
                "message": f"syntax_checker_not_found checker={cmd[0]}",
            }

        # The checker's messages are the product result the agent fixes the file from: kept, redacted.
        output = redact_process_output(stderr or stdout).strip()
        valid = proc.returncode == 0

        errors = []
        if not valid and output:
            for line in output.splitlines()[:20]:
                match = re.search(r"[:\s](\d+)[:\s]", line)
                lineno = int(match.group(1)) if match else None
                errors.append({"line": lineno, "message": line})

        return {
            "path": str(file_path),
            "language": language,
            "valid": valid,
            "errors": errors,
        }
