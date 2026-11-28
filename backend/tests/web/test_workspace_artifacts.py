from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.web._helpers.workspace_artifacts import (
    _safe_upload_name,
    _serialize_session_workspace_files,
    _serialize_tool_artifacts,
)
from app.web._helpers.workspace_file_payloads import _build_workspace_file_payload


@dataclass
class _DummyToolCall:
    result: dict
    tool_name: str = "write_file"
    created_at: datetime = datetime(2026, 4, 19, tzinfo=UTC)


def test_serialize_tool_artifacts_parses_stdout_and_deduplicates_paths(tmp_path: Path) -> None:
    artifact = tmp_path / "notes.txt"
    artifact.write_text("hello", encoding="utf-8")
    tool_call = _DummyToolCall(
        result={
            "stdout": f"Saved to: {artifact}\nWritten to: {artifact}\n",
        }
    )

    serialized = _serialize_tool_artifacts(tool_call, workspace_root=tmp_path)

    assert len(serialized) == 1
    assert serialized[0]["path"] == str(artifact)
    assert serialized[0]["name"] == "notes.txt"
    assert serialized[0]["sizeBytes"] == artifact.stat().st_size


def test_serialize_tool_artifacts_exposes_diagram_artifact() -> None:
    tool_call = _DummyToolCall(
        tool_name="create_diagram",
        result={
            "preview": {
                "compact_result": {
                    "diagram_id": "abc12345",
                    "title": "AWS Topology",
                    "diagram_xml": "<mxGraphModel><root><mxCell id=\"0\"/></root></mxGraphModel>",
                }
            }
        },
    )

    serialized = _serialize_tool_artifacts(tool_call)

    assert serialized == [
        {
            "name": "AWS-Topology.drawio",
            "path": "diagram://abc12345",
            "mediaType": "text/html",
            "sizeBytes": 58,
            "url": "/chat/api/artifact-preview?path=diagram%3A%2F%2Fabc12345",
        }
    ]


def test_serialize_session_workspace_files_uses_relative_paths_with_workspace_root(tmp_path: Path) -> None:
    artifact = tmp_path / "reports" / "summary.md"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("# Summary\n", encoding="utf-8")
    tool_call = _DummyToolCall(result={"artifacts": [{"path": str(artifact)}]})

    files = _serialize_session_workspace_files([tool_call], workspace_root=tmp_path)

    assert len(files) == 1
    assert files[0]["relativePath"] == "reports/summary.md"
    assert files[0]["parentPath"] == "reports"
    assert files[0]["depth"] == 1


def test_safe_upload_name_strips_path_and_invalid_characters() -> None:
    assert _safe_upload_name("../Quarterly Plan?.pptx") == "Quarterly-Plan.pptx"


def test_build_workspace_file_payload_falls_back_to_filename_outside_workspace(tmp_path: Path) -> None:
    artifact = tmp_path / "outside.txt"
    artifact.write_text("hello", encoding="utf-8")

    payload = _build_workspace_file_payload(
        artifact={"path": str(artifact), "url": "/artifact"},
        tool_name="write_file",
        created_at=datetime(2026, 4, 19, tzinfo=UTC),
        workspace_root=tmp_path / "workspace",
    )

    assert payload["relativePath"] == "outside.txt"
    assert payload["parentPath"] == ""
    assert payload["depth"] == 0
