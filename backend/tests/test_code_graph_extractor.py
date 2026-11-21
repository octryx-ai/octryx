from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import CodeGraphFile, CodeGraphStaleness, Project
from app.services.code_intelligence.graph_extractor import build_native_code_graph_payload
from app.services.code_intelligence.graph_language_extractors import list_native_language_extractors
from app.services.code_intelligence.indexing import (
    run_code_index,
)
from app.services.code_intelligence.repository import (
    create_code_repository,
)


def _snapshot_for(paths: list[tuple[str, str, str]], repo_root: Path) -> dict[str, object]:
    files = []
    for relative_path, language, _content in paths:
        text = (repo_root / relative_path).read_text(encoding="utf-8")
        files.append(
            {
                "path": relative_path,
                "language": language,
                "line_count": text.count("\n") + 1,
                "size_bytes": len(text.encode("utf-8")),
            }
        )
    return {"files": files}


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_native_extractor_registry_covers_issue_131_languages() -> None:
    extractors = list_native_language_extractors()
    languages = {language for extractor in extractors for language in extractor["languages"]}

    assert {"python", "typescript", "javascript", "java"} <= languages
    assert {extractor["name"] for extractor in extractors} >= {
        "python_ast_fastapi",
        "typescript_regex_express",
        "javascript_regex_express",
        "java_tree_sitter_spring",
    }


GOLDEN_SOURCE_FILES = [
    (
        "app/api.py",
        "python",
        "from fastapi import FastAPI\n"
        "\n"
        "app = FastAPI()\n"
        "\n"
        "class Handler:\n"
        "    def handle(self) -> str:\n"
        "        return helper()\n"
        "\n"
        "def helper() -> str:\n"
        "    return 'ok'\n"
        "\n"
        "@app.get('/health')\n"
        "def health() -> str:\n"
        "    return helper()\n",
    ),
    (
        "web/component.ts",
        "typescript",
        "import { renderTitle } from './view';\n"
        "export class Panel {}\n"
        "export const App = () => renderTitle();\n"
        "function webHandler() { return App(); }\n"
        "router.get('/web', webHandler);\n",
    ),
    (
        "web/view.ts",
        "typescript",
        "export function renderTitle(): string {\n  return 'title';\n}\n",
    ),
    (
        "web/routes.tsx",
        "typescript",
        "import { Route } from 'react-router-dom';\n"
        "export function Dashboard() { return <main>Dashboard</main>; }\n"
        "export function Routes() {\n"
        "  return <Route path=\"/dashboard\" element={<Dashboard />} />;\n"
        "}\n",
    ),
    (
        "src/main/java/com/example/GreetingController.java",
        "java",
        "package com.example;\n"
        "import org.springframework.web.bind.annotation.GetMapping;\n"
        "interface GreeterApi {}\n"
        "class GreetingController implements GreeterApi {\n"
        "  private String prefix;\n"
        "  @GetMapping(\"/java\")\n"
        "  public String javaRoute() {\n"
        "    return javaService();\n"
        "  }\n"
        "  public String javaService() { return prefix; }\n"
        "}\n",
    ),
    (
        "tests/test_broken.py",
        "python",
        "def broken(:\n    pass\n",
    ),
    (
        "src/generated/client.generated.ts",
        "typescript",
        "export function generatedClient() { return 'generated'; }\n",
    ),
    (
        "vendor/lib.js",
        "javascript",
        "function vendored() { return 'vendor'; }\n",
    ),
]


def test_native_extractor_builds_python_typescript_java_golden_payload(tmp_path: Path) -> None:
    files = GOLDEN_SOURCE_FILES
    for relative_path, _language, content in files:
        _write(tmp_path / relative_path, content)

    payload = build_native_code_graph_payload(repo_root=tmp_path, snapshot=_snapshot_for(files, tmp_path))
    nodes = payload["nodes"]
    edges = payload["edges"]
    file_nodes = {node["path"]: node for node in nodes if node["kind"] == "file"}
    symbols = {(node["kind"], node["label"]): node for node in nodes if node["kind"] != "file"}
    route_frameworks = {node["metadata"]["framework"] for node in nodes if node["kind"] == "route"}
    relations = {edge["kind"] for edge in edges}

    assert file_nodes["tests/test_broken.py"]["metadata"]["is_test"] is True
    assert file_nodes["tests/test_broken.py"]["metadata"]["parse_status"] == "error"
    assert "SyntaxError" in file_nodes["tests/test_broken.py"]["metadata"]["parse_error"]
    assert file_nodes["src/generated/client.generated.ts"]["metadata"]["is_generated"] is True
    assert file_nodes["src/generated/client.generated.ts"]["metadata"]["index_priority"] == "low"
    assert file_nodes["vendor/lib.js"]["metadata"]["is_vendor"] is True

    assert ("class", "Handler") in symbols
    assert ("function", "helper") in symbols
    assert ("class", "Panel") in symbols
    assert ("function", "App") in symbols
    assert ("function", "Dashboard") in symbols
    assert ("package", "com.example") in symbols
    assert ("interface", "GreeterApi") in symbols
    assert ("class", "GreetingController") in symbols
    assert ("field", "prefix") in symbols
    assert ("method", "javaRoute") in symbols
    assert {"fastapi", "express", "spring", "react_router"} <= route_frameworks
    assert {"defines", "contains", "imports", "calls", "routes_to"} <= relations


@pytest.mark.asyncio
async def test_native_indexing_persists_parse_failures_without_aborting(db, tmp_path: Path) -> None:
    project = Project(
        id=str(uuid.uuid4()),
        name="native-extractor-parse-errors",
        description="test project",
        is_active=True,
        config={},
    )
    db.add(project)
    await db.commit()

    _write(tmp_path / "src" / "ok.py", "def ok() -> str:\n    return 'ok'\n")
    _write(tmp_path / "tests" / "test_broken.py", "def broken(:\n    pass\n")

    created = await create_code_repository(
        db,
        {
            "project_id": project.id,
            "name": "parse-error-workspace",
            "repo_root": str(tmp_path),
            "provider": "local",
            "index_backend": "ripgrep",
            "semantic_backend": "regex",
            "structure_backend": "regex",
            "graph_backend": "code_graph",
        },
    )

    indexed = await run_code_index(db, repository_id=created["id"], force=True, trigger="test")

    assert indexed["repository"]["last_index_status"] == "ready"
    broken_file = (
        await db.execute(select(CodeGraphFile).where(CodeGraphFile.file_path == "tests/test_broken.py"))
    ).scalar_one()
    assert broken_file.parse_error is not None
    assert "SyntaxError" in broken_file.parse_error
    assert broken_file.file_metadata["is_test"] is True
    assert broken_file.file_metadata["parse_status"] == "error"

    staleness = (
        await db.execute(
            select(CodeGraphStaleness).where(CodeGraphStaleness.file_path == broken_file.file_path)
        )
    ).scalar_one()
    assert staleness.status == "error"
    assert "SyntaxError" in staleness.reason
