"""A small local llama.cpp model on the person's Mac, used only to measure a routing suggestion.
Loopback only, a per-start API key in the environment (argv shows in ``ps``), SHA-256-pinned model files."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import secrets
import shutil
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("octryx_claude.local_model")



@dataclass(frozen=True)
class ModelSpec:
    key: str
    repo: str
    revision: str
    file: str
    size: int
    sha256: str
    protocol: str  # "chat" (OpenAI chat with log probabilities) or "systemone" (Liquid AI's decision endpoint)
    license: dict[str, Any] = field(default_factory=dict)  # id, url, note, commercial_restriction, permissive

    @property
    def url(self) -> str:
        return f"https://huggingface.co/{self.repo}/resolve/{self.revision}/{self.file}"

    @property
    def name(self) -> str:
        return f"{self.repo}:{self.file}"

    @property
    def permissive(self) -> bool:
        return self.license.get("permissive") is True


QWEN3_1_7B = ModelSpec(
    key="qwen3-1.7b", repo="Qwen/Qwen3-1.7B-GGUF", revision="90862c4b9d2787eaed51d12237eafdfe7c5f6077",
    file="Qwen3-1.7B-Q8_0.gguf", size=1834426016,
    sha256="061b54daade076b5d3362dac252678d17da8c68f07560be70818cace6590cb1a", protocol="chat",
    license={"id": "Apache-2.0", "url": "https://www.apache.org/licenses/LICENSE-2.0",
             "note": "Apache License 2.0: commercial use allowed.", "commercial_restriction": None, "permissive": True})
D1_2B = ModelSpec(
    key="d1-2b", repo="LiquidAI/d1-2B-GGUF", revision="4a181094d1b6addfaa3a0956f78e7ab2aa406a0c",
    file="d1-2B-Q8_0.gguf", size=1846240576,
    sha256="073313d92b53b0ac8193db6e906cb3c78a98183d244b15b7b8f5426115c6738c", protocol="systemone",
    license={"id": "LFM-Open-1.0", "url": "https://huggingface.co/LiquidAI/d1-2B-GGUF",
             "note": "LFM Open License v1.0: commercial use is allowed only for companies with less than USD 10 "
                     "million annual revenue. Check that your company qualifies before you use it.",
             "commercial_restriction": "annual revenue below USD 10M", "permissive": False})
MODELS = {spec.key: spec for spec in (QWEN3_1_7B, D1_2B)}
ROUTER_MODEL = QWEN3_1_7B
DECISION_MODEL = ROUTER_MODEL.name  # what ``device router status`` shows by default
IDLE_SECONDS = 15 * 60
START_TIMEOUT = 600.0  # the first start downloads the model
REQUEST_TIMEOUT = 10.0
HOST = "127.0.0.1"
_CANDIDATES = ("/opt/homebrew/bin/llama-server", "/usr/local/bin/llama-server")


def find_llama_server() -> str:
    found = shutil.which("llama-server")
    if found:
        return found
    return next((path for path in _CANDIDATES if os.access(path, os.X_OK)), "")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((HOST, 0))
        return int(probe.getsockname()[1])


def server_command(binary: str, *, port: int, model_path: Path, chat: bool = False) -> list[str]:
    # The API key goes in the environment, never argv; --jinja lets a chat model switch thinking off.
    return [binary, "-m", str(model_path), "-b", "8192", "-ub", "8192", *(["--jinja"] if chat else []),
            "--host", HOST, "--port", str(port)]


def server_env(api_key: str, base: dict[str, str] | None = None) -> dict[str, str]:
    env = {key: value for key, value in (os.environ if base is None else base).items()
           if not key.startswith("LLAMA_")}  # nothing of the person's own llama.cpp setup (another host, …)
    env["LLAMA_API_KEY"] = api_key
    return env


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _verified(path: Path, spec: ModelSpec) -> bool:
    try:
        info = path.stat()
    except OSError:
        return False
    if info.st_size != spec.size:
        return False
    stamp = path.with_name(path.name + ".verified")
    expected = f"{spec.sha256} {info.st_size} {info.st_mtime_ns}"
    with contextlib.suppress(OSError):
        if stamp.read_text(encoding="utf-8") == expected:
            return True
    if _sha256(path) != spec.sha256:
        return False
    with contextlib.suppress(OSError):
        stamp.write_text(expected, encoding="utf-8")
    return True


def model_path(models_dir: Path, *, home: Path | None = None, spec: ModelSpec = ROUTER_MODEL) -> Path | None:
    own = models_dir / spec.file
    if _verified(own, spec):
        return own
    cached = ((home or Path.home()) / ".cache" / "huggingface" / "hub" / f"models--{spec.repo.replace('/', '--')}" /
              "snapshots" / spec.revision / spec.file)
    with contextlib.suppress(OSError):
        if cached.exists() and _verified(cached.resolve(), spec):
            return cached.resolve()
    return None


def download_model(models_dir: Path, *, progress: Callable[[int, int], None] | None = None,
                   client: Any = None, spec: ModelSpec = ROUTER_MODEL) -> Path:
    models_dir.mkdir(parents=True, exist_ok=True)
    target, partial = models_dir / spec.file, models_dir / f"{spec.file}.part"
    digest, received = hashlib.sha256(), 0
    http = client or httpx.Client(follow_redirects=True, timeout=httpx.Timeout(30.0, read=120.0))
    try:
        with http.stream("GET", spec.url) as response, partial.open("wb") as handle:
            response.raise_for_status()
            for chunk in response.iter_bytes(4 * 1024 * 1024):
                received += len(chunk)
                if received > spec.size:
                    raise RuntimeError("model_too_large")
                digest.update(chunk)
                handle.write(chunk)
                if progress is not None:
                    progress(received, spec.size)
    finally:
        if client is None:
            http.close()
    if received != spec.size or digest.hexdigest() != spec.sha256:
        partial.unlink(missing_ok=True)
        raise RuntimeError("model_checksum_mismatch")
    os.replace(partial, target)
    _verified(target, spec)
    return target


class LocalModel:
    def __init__(self, models_dir: Path, *, spawn: Callable[..., Any] | None = None,
                 http_factory: Callable[..., Any] | None = None, clock: Callable[[], float] = time.monotonic,
                 idle_seconds: float = IDLE_SECONDS, home: Path | None = None, spec: ModelSpec = ROUTER_MODEL) -> None:
        self.models_dir = models_dir
        self.spec = spec
        self.home = home
        self._spawn = spawn or asyncio.create_subprocess_exec
        self._http_factory = http_factory or httpx.AsyncClient
        self.clock = clock
        self.idle_seconds = idle_seconds
        self._process: Any = None
        self._port = 0
        self._key = ""
        self._last_used = 0.0
        self._lock = asyncio.Lock()

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def _start(self) -> None:
        binary = find_llama_server()
        if not binary:
            raise RuntimeError("llama_cpp_not_installed")
        path = await asyncio.to_thread(model_path, self.models_dir, home=self.home, spec=self.spec)
        if path is None:
            raise RuntimeError("model_not_downloaded")  # `octryx-claude device router on` downloads and checks it
        self._port, self._key = free_port(), secrets.token_urlsafe(32)
        self._process = await self._spawn(*server_command(binary, port=self._port, model_path=path,
                                                          chat=self.spec.protocol == "chat"),
                                          env=server_env(self._key), stdin=asyncio.subprocess.DEVNULL,
                                          stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        deadline = self.clock() + START_TIMEOUT
        async with self._http_factory(timeout=5.0) as http:
            while self.clock() < deadline:
                if self._process.returncode is not None:
                    raise RuntimeError("llama_server_exited")
                with contextlib.suppress(httpx.HTTPError):
                    response = await http.get(f"http://{HOST}:{self._port}/health",
                                              headers={"Authorization": f"Bearer {self._key}"})
                    if response.status_code == 200:
                        return
                await asyncio.sleep(1.0)
        await self.stop()
        raise RuntimeError("llama_server_start_timeout")

    async def ask(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            if not self.running:
                await self._start()
            self._last_used = self.clock()
        async with self._http_factory(timeout=REQUEST_TIMEOUT) as http:
            response = await http.post(f"http://{HOST}:{self._port}{path}", content=json.dumps(body),
                                       headers={"Authorization": f"Bearer {self._key}",
                                                "Content-Type": "application/json"})
            response.raise_for_status()
            return response.json()

    async def stop_when_idle(self) -> None:
        if self.running and self.clock() - self._last_used >= self.idle_seconds:
            await self.stop()

    async def stop(self) -> None:
        process, self._process, self._key = self._process, None, ""
        if process is not None and process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.terminate()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(process.wait(), 10)


def chosen_model(device: dict[str, Any]) -> ModelSpec:
    return MODELS.get(str(device.get("router_model") or ""), ROUTER_MODEL)


def usable(spec: ModelSpec, device: dict[str, Any], *, permissive_only: bool) -> bool:
    if spec.permissive:
        return True
    return not permissive_only and device.get("router_licence_accepted") == spec.license.get("id")


__all__ = ["D1_2B", "DECISION_MODEL", "MODELS", "QWEN3_1_7B", "ROUTER_MODEL", "LocalModel", "ModelSpec",
           "chosen_model", "download_model", "find_llama_server", "model_path", "server_command", "server_env",
           "usable"]
