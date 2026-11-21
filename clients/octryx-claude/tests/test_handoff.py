"""Root freeze 3c (client): the WIP branch, push policy, bundle fallback, /handoff, handoff_now, resume.

Git runs only on temporary repositories; the "remote" is a local bare repository, never a real remote. The
platform is an ``httpx.MockTransport`` that records every request.
"""

from __future__ import annotations

import pytest

from octryx_claude.work_state import WorkStateError, capture_work_state, create_branch, is_secret_path
from tests.handoff_support import git, repos, snapshot  # noqa: F401

from .gitrepo import requires_git

pytestmark = requires_git


# --- the WIP commit ---------------------------------------------------------------------------------------------


def test_the_wip_commit_leaves_the_users_tree_index_and_branch_byte_identical(repos):  # noqa: F811
    user = repos["user"]
    before = snapshot(user)
    work = capture_work_state(user, user_name="Anna", user_email="anna@example.test", message="WIP handoff of BRD-6")
    create_branch(user, "octryx-handoff/BRD-6/Anna-20261006-1030", work.wip_commit)
    after = snapshot(user)

    assert after == before
    assert work.base_commit == before["head"] and work.wip_commit != work.base_commit
    assert git(user, "rev-parse", "refs/heads/octryx-handoff/BRD-6/Anna-20261006-1030") == work.wip_commit
    assert git(user, "log", "-1", "--format=%an <%ae> %s", work.wip_commit) == \
        "Anna <anna@example.test> WIP handoff of BRD-6"
    tree = git(user, "ls-tree", "-r", "--name-only", work.wip_commit).splitlines()
    assert git(user, "show", f"{work.wip_commit}:src/app.py") == "print('v2 work in progress')"
    assert git(user, "show", f"{work.wip_commit}:README.md") == "# demo\nstaged line"
    assert "src/new_module.py" in tree and "build/out.bin" not in tree  # untracked yes, ignored never
    with pytest.raises(WorkStateError):  # create-only: an existing branch is never moved
        create_branch(user, "octryx-handoff/BRD-6/Anna-20261006-1030", work.base_commit)


def test_secret_paths_are_always_left_out_and_reported_by_name(repos):  # noqa: F811
    user = repos["user"]
    work = capture_work_state(user, user_name="Anna", user_email="a@example.test", message="WIP")
    tree = git(user, "ls-tree", "-r", "--name-only", work.wip_commit).splitlines()

    assert work.excluded_files == [".aws/credentials", ".env", "config/.env.local", "id_rsa", "settings.pem"]
    assert not {".env", "config/.env.local", ".aws/credentials", "id_rsa"} & set(tree)
    assert git(user, "show", f"{work.wip_commit}:settings.pem") == "committed key"  # a tracked secret stays at HEAD
    assert set(work.changed_files) == {"README.md", "src/app.py", "src/new_module.py"}
    for path in ("a/.env.production", "deploy/server.key", "x/.ssh/config", "home/.netrc", "id_ed25519.pub"):
        assert is_secret_path(path), path
    for path in ("environment.md", "src/env.py", "keyboard.py", "docs/credentials-guide.md"):
        assert not is_secret_path(path), path


def test_a_clean_tree_hands_over_head(repos):  # noqa: F811
    user = repos["user"]
    git(user, "stash", "-u", "-q")
    work = capture_work_state(user, user_name="Anna", user_email="a@example.test", message="WIP")
    assert work.wip_commit == work.base_commit and work.changed_files == []
