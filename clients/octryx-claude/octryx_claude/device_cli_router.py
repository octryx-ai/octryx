"""``octryx-claude device router``: the local decision model that suggests a model and effort per turn."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from . import device_state
from .device_cli_common import _fail, _update
from .state import LocalState


def _licence_refusal(args: argparse.Namespace, state: LocalState, device: dict, spec: Any) -> int | None:
    if spec.permissive or device.get("router_licence_accepted") == spec.license["id"]:
        return None
    print(f"{spec.name} is under {spec.license['id']}: {spec.license['note']}\n  {spec.license['url']}\n"
          "Your platform may also allow only permissively licensed local models; then this model is not used.")
    if not args.accept_licence:
        return _fail("not downloaded: run again with --accept-licence to accept this licence")
    if _update(state, router_licence_accepted=spec.license["id"]) is None:
        return _fail("this device is not enabled")
    return None


def _download(models_dir: Path, spec: Any) -> int | None:
    from .local_model import download_model, model_path  # noqa: PLC0415

    if model_path(models_dir, spec=spec) is not None:
        return None
    print(f"Downloading {spec.name} ({spec.size / 1e9:.1f} GB, pinned revision, SHA-256 checked, "
          f"licence {spec.license['id']}) …")

    def progress(done: int, total: int) -> None:
        sys.stdout.write(f"\r  {done * 100 // total:3d} %")
        sys.stdout.flush()

    try:
        download_model(models_dir, progress=progress, spec=spec)
    except Exception as exc:  # noqa: BLE001 - shown to the person, nothing unverified is kept
        return _fail(f"download failed: {exc}")
    print()
    return None


def _ask_model(models_dir: Path, spec: Any, prompt: str) -> dict | None:
    import asyncio  # noqa: PLC0415

    from .local_model import LocalModel  # noqa: PLC0415
    from .router import suggest  # noqa: PLC0415

    async def ask() -> dict | None:
        model = LocalModel(models_dir, spec=spec)
        try:
            return await suggest(model, prompt)
        finally:
            await model.stop()

    return asyncio.run(ask())


def run_router(args: argparse.Namespace, state: LocalState) -> int:
    from .local_model import MODELS, chosen_model, find_llama_server  # noqa: PLC0415

    device = device_state.load_device(state)
    if args.model and args.model not in MODELS:
        return _fail(f"unknown model {args.model!r}; choose one of: {', '.join(MODELS)}")
    spec = MODELS[args.model] if args.model else chosen_model(device)
    if args.router_action == "status":
        print(f"router: {'on' if device.get('router') else 'off'} · model {spec.name} · licence {spec.license['id']} · "
              f"llama.cpp {'found' if find_llama_server() else 'missing (brew install llama.cpp)'}")
        return 0
    if args.router_action == "off":
        if _update(state, router=False) is None:
            return _fail("this device is not enabled")
        print("Router off.")
        return 0
    if not find_llama_server():
        return _fail("llama.cpp is not installed: brew install llama.cpp")
    if (refused := _licence_refusal(args, state, device, spec)) is not None:
        return refused
    models_dir = state.root / "models"
    if (failed := _download(models_dir, spec)) is not None:
        return failed
    if args.router_action == "on":
        print("Starting the local decision model …")
        if _ask_model(models_dir, spec, "warm up") is None:
            return _fail("the local model did not answer; see `octryx-claude device logs`")
        if _update(state, router=True, router_model=spec.key) is None:
            return _fail("this device is not enabled")
        print("Router on: every Mac turn gets a suggested model and effort (shown in the app; your choice still runs).")
        return 0
    if not args.prompt:
        return _fail('router try needs a prompt, e.g. octryx-claude device router try "fix the failing test"')
    route = _ask_model(models_dir, spec, args.prompt)
    if route is None:
        return _fail("no answer from the local model")
    print(f"{route['tier']} ({route['confidence']:.0%}) → {route['suggested_model']} · {route['suggested_effort']} "
          f"· {route['ms']} ms")
    return 0
