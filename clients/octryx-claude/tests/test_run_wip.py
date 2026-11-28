from __future__ import annotations

from octryx_claude.run_wip import push_run_wip, restore_run_wip, wip_branch
from tests.handoff_support import git, repos  # noqa: F401 - the shared temporary repositories

from .gitrepo import requires_git

RUN = "8f2d50c4-4546-4f19-9307-03f0d40c9158"
pytestmark = requires_git


def test_the_wip_is_pushed_as_fast_forwards_and_restored_on_another_clone(repos):  # noqa: F811
    user, receiver, remote = repos["user"], repos["receiver"], repos["remote"]
    first = push_run_wip(str(user), RUN)
    assert first["state"] == "pushed" and first["branch"] == wip_branch(RUN) == f"octryx-wip/{RUN}"
    assert git(remote, "rev-parse", f"refs/heads/octryx-wip/{RUN}") == first["sha"]
    assert git(remote, "rev-parse", "refs/heads/main") != first["sha"]

    assert push_run_wip(str(user), RUN)["state"] == "unchanged"
    (user / "src" / "app.py").write_text("print('v3')\n")
    second = push_run_wip(str(user), RUN)
    assert second["state"] == "pushed"
    assert first["sha"] in git(remote, "rev-list", f"refs/heads/octryx-wip/{RUN}").splitlines()
    tree = git(remote, "ls-tree", "-r", "--name-only", second["sha"]).splitlines()
    assert "src/new_module.py" in tree and ".env" not in tree and "id_rsa" not in tree

    restored = restore_run_wip(receiver, RUN)
    assert restored["state"] == "restored" and restored["sha"] == second["sha"]
    assert (receiver / "src" / "app.py").read_text() == "print('v3')\n"
    assert (receiver / "src" / "new_module.py").read_text() == "NEW = True\n"


def test_restore_never_overwrites_local_changes_and_says_when_there_is_nothing(repos):  # noqa: F811
    receiver = repos["receiver"]
    assert restore_run_wip(receiver, RUN)["state"] == "absent"
    push_run_wip(str(repos["user"]), RUN)
    (receiver / "README.md").write_text("mine\n")
    assert restore_run_wip(receiver, RUN)["state"] == "dirty"
    assert (receiver / "README.md").read_text() == "mine\n"


def test_the_wip_commit_carries_the_runs_ai_trailers(repos):  # noqa: F811
    user, remote = repos["user"], repos["remote"]
    (user / "src" / "app.py").write_text("print('ai')\n")
    trailer = "AI-Generated-By-octryx: claude-haiku-5-5\nOctryx-Run: OCX-20"
    pushed = push_run_wip(str(user), RUN, trailer)
    assert pushed["state"] == "pushed"
    assert trailer in git(remote, "log", "-1", "--format=%B", pushed["sha"])


def test_restore_never_takes_back_what_the_branch_gained_after_the_wip(repos):  # noqa: F811
    user = repos["user"]
    for name in (".env", "id_rsa", "settings.pem"):
        (user / name).unlink(missing_ok=True)
    git(user, "checkout", "-q", "settings.pem")
    pushed = push_run_wip(str(user), RUN)  # the coordinator's turn: app.py, README.md, new_module.py
    assert pushed["state"] == "pushed"
    git(user, "stash", "-q", "--include-untracked")
    (user / "src" / "merged.py").write_text("MERGED = True\n")  # an item merged after the WIP
    (user / "README.md").write_text("# demo\nmerged readme\n")  # the branch changed a file the WIP has too
    git(user, "add", "-A")
    git(user, "commit", "-q", "-m", "Merge item api")

    restored = restore_run_wip(user, RUN)

    assert restored["state"] == "restored" and restored["kept_branch"] == ["README.md"], restored
    assert (user / "src" / "merged.py").read_text() == "MERGED = True\n"  # the merged work stays
    assert (user / "README.md").read_text() == "# demo\nmerged readme\n"  # the branch's newer version wins
    assert (user / "src" / "app.py").read_text() == "print('v2 work in progress')\n"
    assert (user / "src" / "new_module.py").read_text() == "NEW = True\n"
    assert "merged.py" not in git(user, "status", "--porcelain")


def test_a_wip_taken_on_a_commit_the_branch_no_longer_has_is_stale(repos):  # noqa: F811
    user = repos["user"]
    for name in (".env", "id_rsa"):
        (user / name).unlink()
    assert push_run_wip(str(user), RUN)["state"] == "pushed"
    git(user, "stash", "-q", "--include-untracked")
    git(user, "commit", "-q", "--amend", "-m", "rewritten base")  # the WIP's base is not on the branch any more
    assert restore_run_wip(user, RUN)["state"] == "stale"
    assert git(user, "status", "--porcelain") == ""


def test_a_change_of_plan_puts_the_tree_back_to_its_checkpoint_and_keeps_a_backup(repos):  # noqa: F811
    from octryx_claude.run_wip import reset_tree

    user = repos["user"]
    checkpoint = push_run_wip(str(user), RUN)["sha"]  # the work as reproduce left it
    (user / "src" / "app.py").write_text("print('the fix')\n")  # the fix phase's change
    (user / "src" / "fix_helper.py").write_text("HELPER = 1\n")  # a file the fix added
    push_run_wip(str(user), RUN)
    done = reset_tree(user, RUN, checkpoint)
    assert done["state"] == "done" and done["files"] == 2
    assert (user / "src" / "app.py").read_text() == git(user, "show", f"{checkpoint}:src/app.py") + "\n"
    assert not (user / "src" / "fix_helper.py").exists()
    assert (user / ".env").exists() and (user / "id_rsa").exists()  # never in the WIP: never touched
    backup = user / done["backup"]
    assert (backup / "src" / "fix_helper.py").read_text() == "HELPER = 1\n"  # moved, never deleted
    assert (backup / "src" / "app.py").read_text() == "print('the fix')\n"
    assert reset_tree(user, RUN, "f" * 40)["state"] == "failed"
