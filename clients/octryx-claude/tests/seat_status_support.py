"""Shared key and recorded supervise helpers for the seat status tests."""

from __future__ import annotations

from octryx_claude import seat_status, supervisor

KEY = ("0b6c" + "4a52-3b1e-4c1b-9f55-1d1c1b1a1f10")


# --- 1 + 3: the start --------------------------------------------------------------------------------------------

def _supervise_recording(launch_env, monkeypatch, capsys, failure=None):
    seen = {}

    def supervise(argv, env):
        seen["err_before_claude"] = capsys.readouterr().err
        seen["env"] = env
        if failure is not None:
            seat_status.record_failure(launch_env["state"], env["OCTRYX_SESSION_KEY"], failure)
        return 0

    monkeypatch.setattr(supervisor, "supervise", supervise)
    return seen
