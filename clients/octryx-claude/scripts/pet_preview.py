"""Shows the real tray icon with a state from the shared contract examples, without a platform (dev tool).
Usage: python scripts/pet_preview.py needs_you [--open-menu] [--seconds 20]"""

from __future__ import annotations

import argparse
import json
import tempfile
import threading
from pathlib import Path

from octryx_claude.pet import api
from octryx_claude.pet.account import LocalAccount
from octryx_claude.pet.model import parse
from octryx_claude.pet.runner import Runner
from octryx_claude.pet.tray import MACOS, Tray, _on_main
from octryx_claude.state import LocalState

FIXTURE = Path(__file__).resolve().parents[3] / "backend" / "tests" / "fixtures" / "agent_gateway" / "pet_v1.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("example", nargs="?", default="needs_you")
    parser.add_argument("--open-menu", action="store_true")
    parser.add_argument("--seconds", type=float, default=20.0)
    args = parser.parse_args()
    example = json.loads(FIXTURE.read_text(encoding="utf-8"))["examples"][args.example]
    state = LocalState(Path(tempfile.mkdtemp(prefix="octryx-pet-preview-"))).ensure()
    state.write_config({"base_url": "https://octryx.example"})

    def fake_fetch(_state, **_kwargs) -> api.FetchResult:
        return api.FetchResult("ok", pet=parse(example), etag='"preview"')

    tray = Tray(lambda view: Runner(LocalAccount(state), view, fetch=fake_fetch))

    def open_menu() -> None:
        if MACOS:
            _on_main(lambda: tray.icon._status_item.button().performClick_(None))  # noqa: SLF001

    def close_menu() -> None:
        if MACOS:
            _on_main(lambda: tray.icon._status_item.menu().cancelTracking())  # noqa: SLF001

    if args.open_menu:
        threading.Timer(2.0, open_menu).start()
        threading.Timer(6.0, close_menu).start()
    threading.Timer(args.seconds, tray.quit).start()
    tray.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
