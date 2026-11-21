from __future__ import annotations

from app.tools.runtime_impl._runtime_readme_helpers import (
    _build_module_descriptor,
    _collect_key_files,
    _parse_build_file_metadata,
)


def test_parse_build_file_metadata_detects_maven_and_node(tmp_path):
    pom_path = tmp_path / "pom.xml"
    pom_path.write_text(
        "<project><groupId>com.example</groupId><artifactId>demo</artifactId><packaging>war</packaging></project>",
        encoding="utf-8",
    )
    package_path = tmp_path / "package.json"
    package_path.write_text('{"name": "@demo/app", "version": "1.2.3"}', encoding="utf-8")

    assert _parse_build_file_metadata(pom_path) == {
        "kind": "maven",
        "artifact_id": "demo",
        "group_id": "com.example",
        "packaging": "war",
    }
    assert _parse_build_file_metadata(package_path) == {
        "kind": "node",
        "package_name": "@demo/app",
        "version": "1.2.3",
    }


def test_collect_key_files_limits_to_live_identifier_suffixes(tmp_path):
    root = tmp_path / "module"
    (root / "src/main/java").mkdir(parents=True)
    (root / "src/main/resources").mkdir(parents=True)
    (root / "src/test/resources").mkdir(parents=True)
    (root / "src/main/java/App.java").write_text("class App {}", encoding="utf-8")
    (root / "src/main/resources/application.yaml").write_text("name: demo\n", encoding="utf-8")
    (root / "src/test/resources/sample.txt").write_text("ignored\n", encoding="utf-8")

    key_files = _collect_key_files(root)

    assert "src/main/java/App.java" in key_files
    assert "src/main/resources/application.yaml" in key_files
    assert "src/test/resources/sample.txt" not in key_files


def test_build_module_descriptor_uses_canonical_build_file_names(tmp_path):
    repo_root = tmp_path / "repo"
    module_dir = repo_root / "javaagent" / "demo"
    module_dir.mkdir(parents=True)
    (module_dir / "pom.xml").write_text("<project><artifactId>demo</artifactId></project>", encoding="utf-8")

    descriptor = _build_module_descriptor(module_dir, repo_root)

    assert descriptor["build_file_name"] == "pom.xml"
    assert descriptor["kind"] == "javaagent"
    assert descriptor["artifact_id"] == "demo"

