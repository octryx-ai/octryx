"""The hard core of a run's shell: no command writes or removes git's own files (hooks and config would run code on
the platform's git), an environment or anything outside the repository."""

from app.services.workflow_runs.octryx.hard_core import refusal, written_paths
from app.services.workflow_runs.protected_paths import KIND_ENVIRONMENT, KIND_GIT

ROOT = "/work/repo"


def _kind(command: str, cwd: str = ROOT) -> str | None:
    found = refusal(command, cwd, ROOT)
    return found[0] if found else None


def test_writing_into_git_an_environment_or_outside_is_refused_in_every_form():
    for command in ("echo x > .git/config", "printf '#!/bin/sh' >> .git/hooks/pre-commit",
                    "cat <<'EOF' > .git/hooks/post-checkout\nrm -rf /\nEOF", "echo x | tee .git/config",
                    "tee -a .git/info/exclude < notes", "cp evil.sh .git/hooks/pre-push", "mv x .git/HEAD",
                    "install -m 755 x .git/hooks/pre-commit", "ln -s /tmp/x .git/hooks/pre-commit",
                    "sed -i s/a/b/ .git/config", "chmod +x .git/hooks/pre-commit", "touch .gitattributes",
                    "git config core.hooksPath /tmp/hooks", "git remote set-url origin https://evil.example/r.git",
                    "git -C . config credential.helper store", "dd if=x of=.git/config", "rm .git/index"):
        assert _kind(command) == KIND_GIT, command
    for command in ("echo x > .venv/bin/python", "cp shim node_modules/.bin/jest", "rm .venv/bin/pytest"):
        assert _kind(command) == KIND_ENVIRONMENT, command
    for command in ("echo x > ../other/file", "cp a ~/.bashrc", "echo x >> /etc/hosts", "mv a /usr/local/bin/b",
                    "tee $HOME/.profile < a"):
        assert _kind(command) == "outside", command
    assert _kind("echo x > hooks/pre-commit", cwd=f"{ROOT}/.git") == KIND_GIT


def test_normal_developer_work_and_the_temp_folders_pass():
    for command in ("echo x > notes.md", "pytest -q > /tmp/out.txt 2>&1", "npm test 2>&1 | tee /tmp/log",
                    "cp src/a.py src/b.py", "mv old.py new.py", "sed -i s/a/b/ src/app.py", "touch tests/test_x.py",
                    "git config --get remote.origin.url", "git config -l", "git remote -v", "git status",
                    "pytest 2>&1 >/dev/null", "rm tests/test_totals.py", "echo x > src/.gitkeep"):
        assert _kind(command) is None, command
    assert written_paths("cp a b c dest/") == ["dest/"]
    assert set(written_paths("mv a b dest/")) == {"dest/", "a", "b"}
