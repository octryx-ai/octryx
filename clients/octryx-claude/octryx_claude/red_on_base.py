"""The run's confirmed tests once more on its base commit, so the platform proves a reproduction on unchanged code.
Only the confirmed test files run, with the repository's own setup and test command; nothing stays behind."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

TIMEOUT = 900
MAX_XML_CHARS = 512 * 1024
TAIL_CHARS = 20_000


def _git(root: Path, *args: str) -> bool:
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=120,
                              check=False).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _module(name: str) -> str:
    return name[:-3].replace("/", ".") if name.endswith(".py") else ""


def _prefix_end(test: str, prefix: list[str]) -> int | None:
    import re  # noqa: PLC0415

    found = re.search(r"(?:^|\s)" + r"\s+".join(re.escape(word) for word in prefix) + r"(?=\s|$)", test)
    return found.end() if found else None


def _command(environment: dict[str, Any], commands: list[str], files: list[str],
             templates: list[dict[str, Any]] | None = None) -> str:
    # Appending files is never guessed: unittest discover reads an appended file as its start folder.
    import shlex  # noqa: PLC0415

    test = str(environment.get("test") or (commands[0] if commands else "")).strip()
    if not test or not files:
        return ""
    for spec in templates or []:
        if spec.get("contains") and str(spec["contains"]) not in test.split():
            continue
        if spec.get("lacks") and str(spec["lacks"]) in test.split():
            continue
        if spec.get("single_file") and len(files) != 1:
            continue
        end = next((at for prefix in spec.get("commands") or [] if (at := _prefix_end(test, list(prefix)))), None)
        if end is None:
            continue
        argv = str(spec.get("argv") or "")
        modules = [_module(name) for name in files]
        if "{modules}" in argv and not all(modules):
            return test  # a file the module form cannot name: the full run
        return (argv.replace("{test}", test).replace("{prefix}", test[:end])
                .replace("{files}", " ".join(shlex.quote(name) for name in files))
                .replace("{basename}", shlex.quote(files[0].rsplit("/", 1)[-1]))
                .replace("{modules}", " ".join(shlex.quote(name) for name in modules)))
    return test


def run(request: dict[str, Any], root: Path, app_folder: str, environment: dict[str, Any],
        commands: list[str]) -> dict[str, Any]:
    from . import environment_file  # noqa: PLC0415
    from .pipeline_commands import _env  # noqa: PLC0415

    files = [str(name) for name in request.get("files") or []]
    command = _command(environment, commands, files, list(request.get("only_files") or []))
    base = str(request.get("base") or "")
    if not command or not base:
        return {"reason": "no test command or base commit"}
    root = Path(root).resolve()
    worktree = Path(tempfile.mkdtemp(prefix="octryx-red-on-base-")) / "tree"
    if not _git(root, "worktree", "add", "--detach", str(worktree), base):
        shutil.rmtree(worktree.parent, ignore_errors=True)
        return {"reason": "the base commit could not be checked out"}
    try:
        folder = worktree / app_folder if app_folder not in ("", ".") else worktree
        for name in files:  # this change's version of each confirmed test file
            source, target = root / app_folder / name, folder / name
            if source.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        env = _env(folder, list(environment.get("path") or []), environment)
        ready, _log = environment_file.setup(folder, environment, env) if environment else (True, "")
        if not ready:
            return {"reason": "the app folder's setup failed on the base commit", "command": command}
        from .pipeline_commands import report_env_for  # noqa: PLC0415

        report = worktree.parent / "red-on-base.xml"  # the platform's per-test report (stacks.json report_env)
        wanted = {str(key): str(value) for key, value in dict(request.get("report_env") or {}).items()}
        env = report_env_for(env, report, wanted) if wanted else env
        started = time.monotonic()
        try:
            done = subprocess.run(command, shell=True, cwd=folder, env=env, capture_output=True, text=True,  # noqa: S602
                                  timeout=TIMEOUT, check=False)
        except subprocess.TimeoutExpired:
            return {"reason": f"timed out after {TIMEOUT} s", "command": command}
        output = f"{done.stdout}\n{done.stderr}"
        xml = report.read_text(encoding="utf-8", errors="replace") if wanted and report.is_file() else ""
        # Each test named from the app folder, as the platform asked for it (the worktree is a temporary folder).
        xml = xml.replace(f"{folder.resolve()}/", "").replace(f"{folder}/", "")
        report_xml = {"junit_xml": xml} if xml and len(xml) <= MAX_XML_CHARS else {}
        return {"command": command, "exit_code": done.returncode, "seconds": round(time.monotonic() - started, 1),
                "output_tail": output[-TAIL_CHARS:], **report_xml}
    finally:
        _git(root, "worktree", "remove", "--force", str(worktree))
        shutil.rmtree(worktree.parent, ignore_errors=True)  # our own temporary folder


def for_view(view: dict[str, Any], root: Path) -> dict[str, Any] | None:
    if not view.get("red_on_base"):
        return None
    from . import environment_file  # noqa: PLC0415

    pointer = dict(view.get("environment_file") or {})
    account = environment_file.read(Path(root), str(pointer.get("file") or "")) if pointer else {"state": "missing"}
    if account.get("state") != environment_file.OK:
        return {"reason": "the environment file is not usable for the base run"}
    try:
        return run(dict(view["red_on_base"]), Path(root), str(account["app_folder"]), dict(account["environment"]),
                   list(account.get("commands") or []))
    except Exception as error:  # noqa: BLE001 - the platform pauses with the reason
        return {"reason": f"the base run failed: {type(error).__name__}"}


__all__ = ["for_view", "run"]
