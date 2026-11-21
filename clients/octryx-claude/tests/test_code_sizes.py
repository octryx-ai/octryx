"""The launcher counts what the Workspace's code limits judge: lines of each changed file, long Python functions."""

from __future__ import annotations

import subprocess
from pathlib import Path

from octryx_claude.contract_sizes import sizes
from octryx_claude.run_contract import facts


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()


def _repo(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    (root / "old.py").write_text("x = 1\n" * 500)  # big, but unchanged: never reported
    (root / "keep.py").write_text("a = 1\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    return root, _git(root, "rev-parse", "HEAD")


def test_only_added_or_modified_text_files_are_counted_with_their_long_functions(tmp_path):
    root, base = _repo(tmp_path)
    body = "\n".join(f"    v{i} = {i}" for i in range(45))
    (root / "keep.py").write_text(f"class Handler:\n    def do_post(self):\n{body.replace('    ', '        ')}\n"
                                  f"def short():\n    return 1\n")
    (root / "new.js").write_text("const a = 1;\n" * 12)
    (root / "blob.bin").write_bytes(b"\xff\xfe\x00")
    counted = sizes(root, base)
    assert counted["files"] == {"keep.py": 49, "new.js": 12}  # old.py unchanged, binary skipped
    assert counted["functions"] == [["keep.py", "Handler.do_post", 46]]  # short() is under the reporting floor
    assert sizes(root, "not-a-sha") == {}


def test_the_stop_facts_carry_the_counts_only_when_the_phase_has_a_code_style(tmp_path, monkeypatch):
    root, base = _repo(tmp_path)
    (root / "keep.py").write_text("a = 2\n")
    contract = {"run": {"current_node": {"id": "work"}, "entry": 3}, "facts": {"base_sha": base},
                "phase": {"protected_files": []}}
    assert "sizes" not in facts(contract, root=root, with_diff=True)
    monkeypatch.setattr("octryx_claude.style_tools.run_tools", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("octryx_claude.style_l10n.l10n_facts", lambda *_args, **_kwargs: None)
    contract["phase"]["code_style"] = {"general": {"max_lines_per_file": 300}, "languages": {}}
    assert facts(contract, root=root, with_diff=True)["sizes"]["files"] == {"keep.py": 1}


def test_the_base_s_long_functions_of_a_modified_file_go_up_too(tmp_path):
    """A function already over its limit at the base only warns unless it grows; the server needs
    its size at the base."""
    root, _base = _repo(tmp_path)
    long_body = "\n".join(f"    v{i} = {i}" for i in range(70))
    (root / "keep.py").write_text(f"def run_s2():\n{long_body}\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "long at the base")
    base = _git(root, "rev-parse", "HEAD")
    shorter = "\n".join(f"    v{i} = {i}" for i in range(64))
    (root / "keep.py").write_text(f"def run_s2():\n{shorter}\n")
    counted = sizes(root, base)
    assert counted["functions"] == [["keep.py", "run_s2", 65]]
    assert counted["base_functions"] == [["keep.py", "run_s2", 71]] and counted["base_files"] == {"keep.py": 71}
