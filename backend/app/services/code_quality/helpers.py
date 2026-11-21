from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.services.code_quality.repo_files import CPP_SOURCE_SUFFIXES, _iter_repo_files

WhichFn = Callable[[str], str | None]

SAST_RUNNER_COMMANDS: dict[str, list[str]] = {
    "bandit": ["bandit", "-r", "."],
    "semgrep": ["semgrep", "--config=auto", "."],
    "gosec": ["gosec", "./..."],
    "spotbugs": ["spotbugs", "-textui", "."],
}

_PRIVATE_DEPENDENCY_PATTERNS = (
    "non-resolvable parent pom",
    "could not resolve dependencies",
    "could not find artifact",
    "failed to read artifact descriptor",
    "could not transfer artifact",
    "authentication failed",
    "authorization failed",
    "401 unauthorized",
    "403 forbidden",
    "pkix path building failed",
)
_CI_RUNTIME_PATTERNS = (
    "cannot connect to the docker daemon",
    "error response from daemon",
    "pull access denied",
    "no matching manifest",
    "imagepullbackoff",
)


def truncate(text: str, *, max_chars: int = 8000) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...[truncated]"


def resolve_validation_gates(config: dict[str, Any]) -> list[dict[str, Any]]:
    raw_gates = config.get("validation_gates")
    if not isinstance(raw_gates, list):
        return []
    gates: list[dict[str, Any]] = []
    for raw_gate in raw_gates:
        if not isinstance(raw_gate, dict):
            continue
        name = str(raw_gate.get("name") or raw_gate.get("id") or "").strip()
        if not name:
            continue
        gate = {key: value for key, value in raw_gate.items() if key not in {"status", "result"}}
        gate["name"] = name
        gate.setdefault("required", True)
        gates.append(gate)
    return gates


def detect_validation_blockers(
    text: str,
    *,
    exit_code: int | None,
    tool_name: str,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    if exit_code == 0:
        return []
    lowered = text.lower()
    blockers: list[dict[str, Any]] = []
    if any(pattern in lowered for pattern in _PRIVATE_DEPENDENCY_PATTERNS):
        blockers.append(
            {
                "code": "private_dependency_access_required",
                "severity": "blocking",
                "tool_name": tool_name,
                "message": "Dependency resolution failed against a private or inaccessible artifact source.",
                "question": (
                    "Which repository credentials, Maven/Gradle settings, or internal registry approvals "
                    "should I use?"
                ),
            }
        )
    if any(pattern in lowered for pattern in _CI_RUNTIME_PATTERNS):
        blockers.append(
            {
                "code": "ci_runtime_access_required",
                "severity": "blocking",
                "tool_name": tool_name,
                "message": "The validation runtime or container image could not be accessed.",
                "question": "Which CI image or runtime access should I use for this validation?",
            }
        )
    if _baseline_gate_required(config) and not any(item["code"].endswith("_access_required") for item in blockers):
        blockers.append(
            {
                "code": "baseline_validation_failed",
                "severity": "blocking",
                "tool_name": tool_name,
                "message": "Baseline validation is not green, so migration results would be ambiguous.",
                "question": (
                    "Should I repair the existing baseline first, or flag the migration separately despite the red "
                    "baseline?"
                ),
            }
        )
    return blockers


def _baseline_gate_required(config: dict[str, Any]) -> bool:
    if bool(config.get("requires_baseline_green")):
        return True
    return any(
        str(gate.get("name") or "").strip().lower() in {"baseline", "baseline_tests", "baseline-test"}
        and bool(gate.get("required", True))
        for gate in resolve_validation_gates(config)
    )


def command_available(command: list[str], cwd: Path, *, which_fn: WhichFn) -> bool:
    if not command:
        return False
    executable = str(command[0]).strip()
    if not executable:
        return False
    if executable.startswith("./") or executable.startswith("../"):
        return (cwd / executable).exists()
    candidate = Path(executable)
    if candidate.is_absolute():
        return candidate.exists()
    return which_fn(executable) is not None


def format_check_command(formatter: str, *, auto_fix: bool) -> list[str] | None:
    normalized = formatter.strip().lower()
    if normalized == "ruff":
        return ["ruff", "format", "."] if auto_fix else ["ruff", "format", "--check", "."]
    if normalized == "black":
        return ["black", "."] if auto_fix else ["black", "--check", "."]
    if normalized == "prettier":
        return ["prettier", "--write" if auto_fix else "--check", "."]
    if normalized == "gofmt":
        return ["gofmt", "-w" if auto_fix else "-l", "."]
    return None


def resolve_java_formatter_command(repo_root: Path, *, auto_fix: bool, which_fn: WhichFn) -> list[str] | None:
    gradlew = repo_root / "gradlew"
    mvnw = repo_root / "mvnw"
    has_gradle_build = any((repo_root / marker).exists() for marker in ("build.gradle", "build.gradle.kts"))
    has_maven_build = (repo_root / "pom.xml").exists()
    if gradlew.exists():
        return ["./gradlew", "spotlessApply" if auto_fix else "spotlessCheck"]
    if mvnw.exists():
        return ["./mvnw", "-q", "spotless:apply" if auto_fix else "spotless:check"]
    if has_gradle_build and which_fn("gradle"):
        return ["gradle", "spotlessApply" if auto_fix else "spotlessCheck"]
    if has_maven_build and which_fn("mvn"):
        return ["mvn", "-q", "spotless:apply" if auto_fix else "spotless:check"]
    if which_fn("google-java-format"):
        java_files = _iter_repo_files(repo_root, {".java"}, max_files=200)
        if not java_files:
            return None
        args = ["google-java-format", "--replace" if auto_fix else "--dry-run"]
        if not auto_fix:
            args.append("--set-exit-if-changed")
        return [*args, *[str(path) for path in java_files]]
    return None


def resolve_maven_command(repo_root: Path, *, which_fn: WhichFn) -> list[str] | None:
    mvnw = repo_root / "mvnw"
    if mvnw.exists() and os.access(mvnw, os.X_OK):
        first_line = (mvnw.read_bytes()[:128].split(b"\n") or [b""])[0]
        if b"\r" not in first_line:
            return ["./mvnw"]
    if which_fn("mvn"):
        return ["mvn"]
    if mvnw.exists():
        return ["sh", "./mvnw"]
    return None


def resolve_gradle_command(repo_root: Path, *, which_fn: WhichFn) -> list[str] | None:
    gradlew = repo_root / "gradlew"
    if gradlew.exists():
        return ["./gradlew"]
    if which_fn("gradle"):
        return ["gradle"]
    return None


def list_openrewrite_report_files(repo_root: Path) -> list[str]:
    report_paths: list[str] = []
    target_root = repo_root / "target"
    build_root = repo_root / "build"
    for base in (target_root, build_root):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if path.name == "rewrite.patch" or path.suffix.lower() in {".csv", ".json", ".html"}:
                report_paths.append(str(path.relative_to(repo_root)))
    return sorted(set(report_paths))


def resolve_go_formatter_command(
    repo_root: Path, *, tool_name: str, auto_fix: bool, which_fn: WhichFn
) -> list[str] | None:
    if not which_fn(tool_name):
        return None
    go_files = _iter_repo_files(repo_root, {".go"}, max_files=400)
    if not go_files:
        return None
    args = [tool_name, "-w" if auto_fix else "-l"]
    return [*args, *[str(path) for path in go_files]]


def resolve_c_family_formatter_command(repo_root: Path, *, auto_fix: bool, which_fn: WhichFn) -> list[str] | None:
    if not which_fn("clang-format"):
        return None
    source_files = _iter_repo_files(repo_root, CPP_SOURCE_SUFFIXES, max_files=200)
    if not source_files:
        return None
    base = ["clang-format"]
    if auto_fix:
        base.append("-i")
    else:
        base.extend(["--dry-run", "--Werror"])
    return [*base, *[str(path) for path in source_files]]


def resolve_c_family_linter_command(repo_root: Path, *, which_fn: WhichFn) -> list[str] | None:
    if not which_fn("clang-tidy"):
        return None
    source_files = _iter_repo_files(repo_root, {".c", ".cc", ".cpp", ".cxx"}, max_files=50)
    if not source_files:
        return None
    command = ["clang-tidy", *[str(path) for path in source_files]]
    if (repo_root / "compile_commands.json").exists():
        command.extend(["-p", str(repo_root)])
    return command


def resolve_sast_runners(config: dict[str, Any]) -> list[str]:
    raw_runners = config.get("sast_runners")
    if isinstance(raw_runners, str) and raw_runners.strip():
        return [raw_runners.strip()]
    if isinstance(raw_runners, (list, tuple, set)):
        return [str(item).strip() for item in raw_runners if str(item).strip()]
    raw_single = str(config.get("sast") or "").strip()
    if raw_single:
        return [raw_single]
    language = str(config.get("language") or "unknown").lower()
    defaults = {
        "python": ["bandit"],
        "javascript": ["semgrep"],
        "typescript": ["semgrep"],
        "go": ["gosec"],
        "java": ["semgrep", "spotbugs"],
    }
    return defaults.get(language, [])
