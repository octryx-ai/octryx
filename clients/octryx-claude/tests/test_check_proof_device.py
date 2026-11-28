from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

from octryx_claude import tool_jobs, tool_run, tree_archive

BACKEND = Path(__file__).resolve().parents[3] / "backend" / "app" / "services"
MISTAKE, FIX = 'import os\nkey = os.environ["PAY_KEY"]\n', "from shop.config import settings\nkey = settings.pay_key\n"
RULE = {"tool": "ast-grep", "language": "python", "rule": {"pattern": "os.environ[$KEY]"}}
AST_GREP = Path(sys.executable).parent / "ast-grep"


def _module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


proof_job = _module("server_proof_job", BACKEND / "check_proposals" / "proof_job.py")
server_archive = _module("server_tree_archive", BACKEND / "devices" / "tree_archive.py")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


def _repo(tmp_path: Path) -> tuple[Path, list[str]]:
    repo = tmp_path / "repo"
    (repo / "shop").mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.test")
    _git(repo, "config", "user.name", "t")
    shas = []
    for text in (MISTAKE, FIX):
        (repo / "shop" / "pay.py").write_text(text)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "x")
        shas.append(_git(repo, "rev-parse", "HEAD"))
    return repo, shas


def _run_on_device(monkeypatch, tmp_path: Path, rule: dict) -> dict:
    assert AST_GREP.exists(), "ast-grep-cli is a declared dependency of the launcher"
    monkeypatch.setattr(tool_run, "_executable", lambda tool_id: str(AST_GREP) if tool_id == "ast-grep" else None)
    repo, (before, after) = _repo(tmp_path)
    cases = [{"archive": "red-1", "side": "red", "commit": before, "paths": ["shop/pay.py"]},
             {"archive": "green-1", "side": "green", "commit": after, "paths": ["shop/pay.py"]}]
    archives = {"rule": server_archive.build_archive([(proof_job.RULE_FILE, proof_job.rule_file(rule))], name="rule")}
    for case in cases:
        archives[case["archive"]] = server_archive.build_from_git(repo, case["commit"], name=case["archive"],
                                                                  paths=case["paths"])

    def fetch(_state, item, dest):  # the archive bytes as the platform serves them, unpacked by the launcher
        tree_archive.unpack(archives[item["name"]].data, dest)
        return Path(dest), ""

    body = {"job_id": "tj_" + "b" * 20, "timeout": 60,
            "archives": [{"name": name, "url": f"/api/v1/devices/archives/{name}", "sha256": archive.sha256}
                         for name, archive in archives.items()],
            "steps": [{**step, "timeout": 60, "outputs": []} for step in proof_job.steps(cases)]}
    kind, answer = tool_jobs.run_job(None, body, fetch=fetch, upload=lambda *a, **k: "unused")
    assert kind == "tool_job_result"
    return proof_job.verdict(cases, answer["steps"], at="now") | {"_before": before, "_after": after}


def test_the_pinned_ast_grep_proves_a_check_red_on_the_mistake_and_green_after_the_fix(monkeypatch, tmp_path):
    found = _run_on_device(monkeypatch, tmp_path, RULE)
    assert found["state"] == "proven", found.get("reason")
    assert found["red_on"] == [{"commit": found["_before"], "path": "shop/pay.py"}]
    assert found["green_on"] == {"commit": found["_after"], "files_checked": 1}


def test_a_check_that_also_flags_the_fix_fails_with_the_flagged_place(monkeypatch, tmp_path):
    too_broad = {**RULE, "rule": {"pattern": "key = $VALUE"}}
    found = _run_on_device(monkeypatch, tmp_path, too_broad)
    assert found["state"] == "failed" and found["reason"] == "flags corrected code: shop/pay.py:2"


def test_a_rule_ast_grep_refuses_fails_and_says_so(monkeypatch, tmp_path):
    found = _run_on_device(monkeypatch, tmp_path, {**RULE, "rule": {"patern": "os.environ[$KEY]"}})
    assert found["state"] == "failed" and "could not run" in found["reason"]


def test_the_job_folder_is_gone_afterwards(monkeypatch, tmp_path):
    seen = []
    original = tool_jobs.tempfile.mkdtemp

    def recorded(*args, **kwargs):
        seen.append(original(*args, **kwargs))
        return seen[-1]

    monkeypatch.setattr(tool_jobs.tempfile, "mkdtemp", recorded)
    _run_on_device(monkeypatch, tmp_path, RULE)
    assert seen and not any(Path(folder).exists() for folder in seen)  # removed whatever happened
