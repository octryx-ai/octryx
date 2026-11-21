"""Self-update on start: check, cache, build, verify, switch, re-exec, failure paths, opt-out, loop guard,
and the device service's idle restart."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import httpx
import pytest

from octryx_claude import self_update, self_update_commands, self_update_lock, self_update_state
from octryx_claude.state import LocalState
from tests.self_update_support import NEW, OLD, Builder, Platform, _release, _update, installed  # noqa: F401

_REAL_WANTS_PET = self_update.wants_pet


class PetFailsBuilder(Builder):
    def __call__(self, argv):
        if any(str(part).startswith("octryx-claude[pet]") for part in argv):
            self.argv.append(list(argv))
            return subprocess.CompletedProcess(list(argv), 1, stdout="", stderr="no pyobjc wheel")
        return super().__call__(argv)


# --- failure paths ---------------------------------------------------------------------------------------------


def _unchanged(installed) -> None:  # noqa: F811
    assert os.readlink(installed["venvs"] / "current") == OLD
    assert not (installed["venvs"] / NEW).exists()


# --- check, build, verify, switch -------------------------------------------------------------------------------


def test_update_builds_verifies_switches_and_prunes(installed):  # noqa: F811
    platform, builder = Platform(_release()), Builder()
    updated = _update(installed, platform, builder=builder)
    venvs = installed["venvs"]
    assert updated.previous == OLD and updated.version == NEW
    assert os.readlink(venvs / "current") == NEW
    assert (installed["state"].root / "installed-version").read_text() == f"{NEW}\n"
    # The previous venv stays for running sessions and rollback; the older one is gone.
    assert sorted(entry.name for entry in venvs.iterdir() if not entry.name.startswith(".")) == sorted(
        ["current", OLD, NEW])
    assert platform.calls == ["/octryx-claude/version", f"/octryx-claude/package/{NEW}"]
    venv_cmd, pip_cmd, probe = builder.argv
    assert venv_cmd[1:] == ["-m", "venv", str(venvs / NEW)]
    assert pip_cmd[0] == str(venvs / NEW / "bin" / "python") and "--no-cache-dir" in pip_cmd
    assert pip_cmd[-1].endswith(f"octryx_claude-{NEW}-py3-none-any.whl")
    assert probe[0] == str(venvs / NEW / "bin" / "python")


def test_uv_builds_like_the_installer(installed, monkeypatch):  # noqa: F811
    monkeypatch.setattr(self_update.shutil, "which", lambda name: "/opt/uv" if name == "uv" else None)
    commands = self_update.build_commands(Path("/v"), Path("/w.whl"), {})
    assert commands == [["/opt/uv", "venv", "--quiet", "--no-cache", "--python", ">=3.11", "/v"],
                        ["/opt/uv", "pip", "install", "--quiet", "--no-cache", "--python", "/v/bin/python", "/w.whl"]]
    override = self_update.build_commands(Path("/v"), Path("/w.whl"), {self_update_commands.PYTHON_OVERRIDE_ENV: "/py"})
    assert override[0] == ["/py", "-m", "venv", "/v"]


def test_the_pet_comes_along_on_macos_unless_left_out(tmp_path):
    assert _REAL_WANTS_PET(tmp_path, "darwin") and not _REAL_WANTS_PET(tmp_path, "linux")
    (tmp_path / self_update.NO_PET_FILE).touch()  # install.sh --no-pet
    assert not _REAL_WANTS_PET(tmp_path, "darwin")


def test_the_pet_extra_installs_like_the_build(monkeypatch, tmp_path):
    wheel = tmp_path / "w.whl"
    # No uv on PATH: the gate's PATH may carry one (nightly found venv-tools/bin/uv).
    monkeypatch.setattr(self_update.shutil, "which", lambda name: None)
    pip = self_update.pet_command(Path("/v"), wheel, {})
    assert pip == ["/v/bin/python", "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
                   "--no-cache-dir", f"octryx-claude[pet] @ {wheel.as_uri()}"]
    monkeypatch.setattr(self_update.shutil, "which", lambda name: "/opt/uv" if name == "uv" else None)
    assert self_update.pet_command(Path("/v"), wheel, {})[:3] == ["/opt/uv", "pip", "install"]


@pytest.mark.parametrize("builder_class", [Builder, PetFailsBuilder])
def test_an_update_keeps_the_pet_and_a_failed_pet_never_blocks_it(installed, monkeypatch, builder_class):  # noqa: F811
    monkeypatch.setattr(self_update, "wants_pet", lambda root, platform=None: True)
    platform, builder = Platform(_release()), builder_class()
    updated = _update(installed, platform, builder=builder)
    assert updated.version == NEW and os.readlink(installed["venvs"] / "current") == NEW
    venv_cmd, pip_cmd, pet_cmd, probe, autostart = builder.argv
    assert pet_cmd[0] == str(installed["venvs"] / NEW / "bin" / "python")
    assert pet_cmd[-1].startswith("octryx-claude[pet] @ file://") and pet_cmd[-1].endswith(".whl")
    assert probe[-2] == "-c"
    # After the switch the pet is turned on and restarted on the new version (unless the person turned it off,
    # which `pet autostart` itself respects; without the extra it removes the login item).
    assert autostart == [str(installed["venvs"] / NEW / "bin" / "octryx-claude"), "pet", "autostart", "--restart"]


def test_same_version_does_nothing(installed):  # noqa: F811
    platform = Platform(_release(OLD))
    assert _update(installed, platform) is None
    assert platform.calls == ["/octryx-claude/version"]


def test_answer_is_cached_for_a_minute(installed):  # noqa: F811
    platform = Platform(_release(OLD))
    for moment in (1_000_000.0, 1_000_000.0 + self_update_state.CACHE_SECONDS - 1):
        _update(installed, platform, now=moment)
    assert platform.version_calls() == 1
    _update(installed, platform, now=1_000_000.0 + self_update_state.CACHE_SECONDS)
    assert platform.version_calls() == 2


def test_an_existing_verified_venv_is_reused(installed):  # noqa: F811
    (installed["venvs"] / NEW / "bin").mkdir(parents=True)
    (installed["venvs"] / NEW / "bin" / "octryx-claude").write_text("#!/bin/sh\n")
    platform, builder = Platform(_release()), Builder()
    assert _update(installed, platform, builder=builder).version == NEW
    assert len(builder.argv) == 1 and f"/octryx-claude/package/{NEW}" not in platform.calls


def test_digest_mismatch_is_refused_and_not_retried_for_an_hour(installed):  # noqa: F811
    platform, warnings = Platform(_release(content=b"what was published"), package=b"something else"), []
    assert _update(installed, platform, warnings=warnings) is None
    _unchanged(installed)
    assert warnings == [f"octryx-claude: update to {NEW} failed (digest_mismatch); running {OLD}"]
    _update(installed, platform, now=1_000_000.0 + 120)
    assert platform.calls.count(f"/octryx-claude/package/{NEW}") == 1
    _update(installed, platform, now=1_000_000.0 + self_update_state.FAILED_RETRY_SECONDS + 1)
    assert platform.calls.count(f"/octryx-claude/package/{NEW}") == 2


@pytest.mark.parametrize(("builder", "code"), [(Builder(fail=True), "build_failed"),
                                                (Builder(reports="9.9.9"), "build_unverified")])
def test_build_failures_keep_the_installed_version(installed, builder, code):  # noqa: F811
    warnings = []
    assert _update(installed, Platform(_release()), builder=builder, warnings=warnings) is None
    _unchanged(installed)
    assert warnings == [f"octryx-claude: update to {NEW} failed ({code}); running {OLD}"]


@pytest.mark.parametrize(("answer", "code"), [
    (httpx.ConnectError("offline"), "offline"),
    (httpx.ReadTimeout("slow"), "timeout"),  # a slow platform is not "offline"
    (httpx.Response(503, json={"state": "needs_configuration"}), "refused_503"),
    (httpx.Response(200, json={"version": NEW}), "malformed"),  # no checksum: never installed
    (httpx.Response(200, json={**_release(), "filename": "../evil.whl"}), "malformed"),
])
def test_unusable_answers_warn_once_per_check(installed, answer, code):  # noqa: F811
    warnings = []
    assert _update(installed, Platform(answer), warnings=warnings) is None
    assert _update(installed, Platform(answer), warnings=warnings, now=1_000_010.0) is None  # cached, silent
    assert warnings == [f"octryx-claude: update check failed ({code}); running {OLD}"]
    _unchanged(installed)


def test_checkout_foreign_prefix_or_missing_platform_never_checks(installed, tmp_path):  # noqa: F811
    platform = Platform(_release())
    state = installed["state"]
    common = {"warn": print, "http": platform.http, "runner": Builder(), "env": {}, "home": installed["home"]}
    assert self_update.update_if_available(state, installed="", prefix=installed["prefix"], **common) is None
    assert self_update.update_if_available(state, installed=OLD, prefix=str(tmp_path), **common) is None
    empty = LocalState(tmp_path / "empty").ensure()
    assert self_update.update_if_available(empty, installed=OLD, prefix=installed["prefix"], **common) is None
    assert platform.calls == []


def test_a_concurrent_update_is_left_alone(installed):  # noqa: F811
    import fcntl

    platform = Platform(_release())
    with open(installed["venvs"] / self_update_lock.LOCK_NAME, "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        assert _update(installed, platform) is None
    _unchanged(installed)


def test_opt_out_env_disables_the_update(installed):  # noqa: F811
    platform = Platform(_release())
    assert _update(installed, platform, env={self_update.AUTO_UPDATE_ENV: "0"}) is None
    assert platform.calls == []
