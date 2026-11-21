"""macOS notifications under octryx's own name: an applet built once with osacompile shows them as "Octryx" (not
"Script Editor"); the text goes through a private queue file, never into a script; without the applet the old
osascript call still shows them."""

from __future__ import annotations

import stat
import types

import pytest

from octryx_claude import mac_notify


class Recorder:
    def __init__(self, fail: str = "") -> None:
        self.calls: list[list[str]] = []
        self.fail = fail

    def __call__(self, args, **_kwargs):
        self.calls.append(list(args))
        if args[0] == "osacompile":
            if self.fail == "osacompile":
                return types.SimpleNamespace(returncode=1)
            app = args[2]
            import pathlib

            (pathlib.Path(app) / "Contents" / "Resources").mkdir(parents=True, exist_ok=True)
            (pathlib.Path(app) / "Contents" / "Info.plist").write_text("<plist/>")
        return types.SimpleNamespace(returncode=0)


@pytest.fixture(autouse=True)
def darwin(monkeypatch):
    monkeypatch.setattr(mac_notify.sys, "platform", "darwin")


def test_the_applet_is_built_once_and_messages_go_through_the_private_queue(tmp_path):
    run = Recorder()
    mac_notify.notify("Octryx", 'Your phone sent "hi" $(rm -rf ~)\nsecond line', root=tmp_path, run=run)
    programs = [call[0] for call in run.calls]
    assert programs == ["osacompile", "plutil", "plutil", "plutil", "codesign", "open"]
    assert ["plutil", "-replace", "LSUIElement", "-bool", "true", str(tmp_path / "Octryx.app/Contents/Info.plist")] \
        in run.calls
    assert run.calls[-1] == ["open", "-g", "-j", str(tmp_path / "Octryx.app")]
    queue = tmp_path / "notify-queue"
    assert stat.S_IMODE(queue.stat().st_mode) == 0o700
    [message] = list(queue.iterdir())
    assert stat.S_IMODE(message.stat().st_mode) == 0o600
    assert message.read_text() == 'Octryx\nYour phone sent "hi" $(rm -rf ~) second line'  # one line, data only
    # no message text in any command line
    assert not any("rm -rf" in " ".join(call) for call in run.calls)

    again = Recorder()
    mac_notify.notify("Octryx", "next", root=tmp_path, run=again)
    assert [call[0] for call in again.calls] == ["open"]  # already built: only started


def test_a_changed_applet_version_is_rebuilt(tmp_path, monkeypatch):
    mac_notify.notify("Octryx", "first", root=tmp_path, run=Recorder())
    monkeypatch.setattr(mac_notify, "VERSION", "999")
    run = Recorder()
    mac_notify.notify("Octryx", "second", root=tmp_path, run=run)
    assert run.calls[0][0] == "osacompile"


def test_without_the_applet_the_old_call_still_shows_it(tmp_path):
    run = Recorder(fail="osacompile")
    mac_notify.notify("Octryx", 'say "hi"', root=tmp_path, run=run)
    assert run.calls[-1] == ["osascript", "-e", 'display notification "say \\"hi\\"" with title "Octryx"']


def test_nothing_happens_off_macos_or_without_a_message(tmp_path, monkeypatch):
    run = Recorder()
    mac_notify.notify("Octryx", "   ", root=tmp_path, run=run)
    monkeypatch.setattr(mac_notify.sys, "platform", "linux")
    mac_notify.notify("Octryx", "hello", root=tmp_path, run=run)
    assert run.calls == []


def test_the_applet_script_reads_the_queue_as_data():
    script = mac_notify.APPLET_SCRIPT
    assert "without altering line endings" in script  # else the title/message split never happens
    assert "run script" not in script and "do shell script body" not in script
    assert 'display notification (item 2 of parts) with title (item 1 of parts)' in script
