"""``knowledge_code_impact`` over MCP: where a version change applies in the client's codebase.

The MCP tool is the chat tool (``tools/knowledge_evidence/code_impact``), with the same resolver,
the same rendering and the same evidence. Over MCP it differs in two explicit ways only:

1. it is built with the connection's launcher session key (``X-Octryx-Session``), so the
   codebase resolver can use the session's **recorded repository binding** from octryx-claude
   (a resolver step);
2. it takes ``files=[{path, content}]``: the build files, configuration and sources the client sends
   explicitly (``knowledge/code/client_files``). This is an MCP-only input and it wins. ``commit``
   may name their commit, and nothing is stored.

``path`` is refused (``path_not_available_over_mcp``): it names a directory on the server, which an
external client does not have. ``files`` together with ``repository`` is ``invalid_request``
(``files_and_repository``).

Every answer adds ``session_bound``: whether the answer's repository is the one the session's
launcher bound.
"""

from __future__ import annotations

from typing import Any

from ..tools.knowledge_evidence._scope import failure, knowledge_scope
from ..tools.knowledge_evidence.code_impact import KnowledgeCodeImpactTool, _answer
from .knowledge.code.client_files import ClientFilesRefusedError, client_file_elements
from .knowledge.code.codebase import Codebase
from .knowledge.code.service import code_impact_for_elements
from .knowledge.ledger.errors import EvidenceLedgerError
from .knowledge.runtime import get_evidence_runtime
from .knowledge.sources.repository_snapshot.binding import valid_commit
from .knowledge.sources.repository_snapshot.session_target import SessionRepositoryTarget, session_repository_target
from .knowledge.temporal.errors import GraphStoreError

CODEBASE_CLIENT_FILES = "client_files"


def _refusal(state: str, reason: str, error: str) -> dict[str, Any]:
    return {"state": state, "reason": reason, "error": error}


class McpKnowledgeCodeImpactTool(KnowledgeCodeImpactTool):
    async def execute(self, params: dict, context: Any) -> dict[str, Any]:
        if params.get("path") is not None:
            return _refusal(
                "invalid_request", "path_not_available_over_mcp",
                "path names a server directory; send files, or start the session with octryx-claude in the checkout.",
            )
        if params.get("files") is not None:
            if params.get("repository") is not None:
                return _refusal("invalid_request", "files_and_repository", "Name either files or a repository.")
            return await self._client_files(params, context)
        answer = await super().execute(params, context)
        if "repository" in answer and isinstance(answer.get("repository"), dict):
            target = await session_repository_target(
                context.db, user_id=str(context.user_id), workspace_id=str(context.project_ids[0]),
                session_key=self._session_key,
            )
            answer["session_bound"] = (
                isinstance(target, SessionRepositoryTarget)
                and target.connector_key == answer["repository"].get("key")
            )
        else:
            answer.setdefault("session_bound", False)
        return answer

    async def _client_files(self, params: dict, context: Any) -> dict[str, Any]:
        scope = await knowledge_scope(params, context)
        if type(scope) is dict:
            return scope
        commit = params.get("commit")
        if commit is not None and valid_commit(commit) is None:
            return _refusal("invalid_request", "commit_invalid", "commit must be a 40-character sha.")
        try:
            sent = client_file_elements(params.get("files"))
        except ClientFilesRefusedError as error:
            return _refusal("invalid_request", error.reason, "The files were refused.")
        try:
            result = await code_impact_for_elements(
                context.db,
                runtime=get_evidence_runtime(),
                scope=scope,
                elements=sent.elements,
                commit=commit,
                product=params.get("product"),
                to_version=params.get("to_version"),
                from_version=params.get("from_version"),
            )
        except EvidenceLedgerError as error:
            return failure(error.state.value)
        except GraphStoreError:
            return failure("unavailable")
        answer = _answer(result, scope, Codebase(CODEBASE_CLIENT_FILES, commit))
        answer["files"] = sent.file_count
        answer["session_bound"] = False
        return answer


__all__ = ["CODEBASE_CLIENT_FILES", "McpKnowledgeCodeImpactTool"]
