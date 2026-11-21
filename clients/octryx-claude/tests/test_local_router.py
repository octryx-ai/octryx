"""The local LLM: the decision model on the Mac, only on localhost with a per-start key,
started on demand and stopped when idle; its routing suggestion is measured alongside a turn, never applied."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from octryx_claude import device_state, local_model
from octryx_claude.device_sdk_events import map_message
from octryx_claude.local_model import LocalModel, download_model, model_path, server_command, server_env
from octryx_claude.router import read_route, route_request, suggest


def test_the_server_listens_only_on_localhost_with_a_key_in_its_environment(tmp_path):
    command = server_command("/opt/homebrew/bin/llama-server", port=54321, model_path=tmp_path / "m.gguf")
    assert command[command.index("--host") + 1] == "127.0.0.1"
    assert command[command.index("-m") + 1] == str(tmp_path / "m.gguf")
    assert "-hf" not in command and "--api-key" not in command  # review: no download by name, no key in ps
    assert "0.0.0.0" not in command
    env = server_env("k" * 43, {"PATH": "/bin", "LLAMA_ARG_HOST": "0.0.0.0", "LLAMA_API_KEY": "old"})
    assert env == {"PATH": "/bin", "LLAMA_API_KEY": "k" * 43}  # the person's own llama.cpp settings never apply


class _Stream:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def __enter__(self) -> _Stream:
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    def iter_bytes(self, size: int):
        yield self.data


class _Client:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def stream(self, method: str, url: str) -> _Stream:
        assert "/resolve/90862c4b9d2787eaed51d12237eafdfe7c5f6077/" in url  # the pinned revision (Qwen3-1.7B)
        return _Stream(self.data)


def test_only_the_pinned_model_is_ever_used(tmp_path, monkeypatch):
    import hashlib
    from dataclasses import replace

    data = b"gguf-test-model"
    spec = replace(local_model.ROUTER_MODEL, size=len(data), sha256=hashlib.sha256(data).hexdigest())
    with pytest.raises(RuntimeError, match="checksum"):
        download_model(tmp_path, client=_Client(b"gguf-evil-model"), spec=spec)  # same size, other bytes
    assert list(tmp_path.iterdir()) == []  # nothing unverified is kept
    assert model_path(tmp_path, home=tmp_path, spec=spec) is None
    path = download_model(tmp_path, client=_Client(data), spec=spec)
    assert model_path(tmp_path, home=tmp_path, spec=spec) == path
    path.write_bytes(b"gguf-evil-model")  # swapped after the download
    assert model_path(tmp_path, home=tmp_path, spec=spec) is None


class _Process:
    def __init__(self) -> None:
        self.returncode = None

    def terminate(self) -> None:
        self.returncode = 0

    async def wait(self) -> int:
        return 0


class _Response:
    def __init__(self, status: int, body: Any = None) -> None:
        self.status_code, self._body = status, body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def json(self) -> Any:
        return self._body


class _Http:
    calls: list[tuple[str, str, dict]] = []

    def __init__(self, **_: Any) -> None:
        pass

    async def __aenter__(self) -> _Http:
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None

    async def get(self, url: str, headers: dict) -> _Response:
        _Http.calls.append(("GET", url, headers))
        return _Response(200)

    async def post(self, url: str, content: str, headers: dict) -> _Response:
        _Http.calls.append(("POST", url, headers))
        return _Response(200, {"answers": {"tier": {"type": "choice", "choice": "hard", "confidence": 0.92,
                                                    "probabilities": {"trivial": 0.01, "normal": 0.07,
                                                                      "hard": 0.92}}}})


def test_started_on_demand_with_a_fresh_key_and_stopped_when_idle(tmp_path, monkeypatch):
    monkeypatch.setattr(local_model, "find_llama_server", lambda: "/bin/llama-server")
    monkeypatch.setattr(local_model, "model_path", lambda models_dir, home=None, spec=None: tmp_path / "m.gguf")
    spawned: list[tuple] = []
    envs: list[dict] = []
    now = [0.0]

    async def spawn(*args: Any, **kwargs: Any) -> _Process:
        spawned.append(args)
        envs.append(kwargs["env"])
        return _Process()

    _Http.calls.clear()
    model = LocalModel(tmp_path, spawn=spawn, http_factory=_Http, clock=lambda: now[0], idle_seconds=60,
                       spec=local_model.D1_2B)  # this fake answers d1-2B's /v1/systemone

    async def scenario() -> None:
        route = await suggest(model, "Pods crashloopen, warum?")
        assert route is not None and route["tier"] == "hard" and route["suggested_model"] == "claude-opus-5-5"
        assert model.running
        key = envs[0]["LLAMA_API_KEY"]
        assert key not in " ".join(spawned[0])
        assert len(key) >= 32 and all(call[2]["Authorization"] == f"Bearer {key}" for call in _Http.calls)
        assert all(call[1].startswith("http://127.0.0.1:") for call in _Http.calls)
        now[0] = 30
        await model.stop_when_idle()
        assert model.running
        now[0] = 100
        await model.stop_when_idle()
        assert not model.running

    asyncio.run(scenario())


def test_no_llama_cpp_or_no_model_means_no_suggestion_and_no_error(tmp_path, monkeypatch):
    monkeypatch.setattr(local_model, "find_llama_server", lambda: "")
    assert asyncio.run(suggest(LocalModel(tmp_path), "anything")) is None
    assert asyncio.run(suggest(LocalModel(tmp_path), "   ")) is None
    monkeypatch.setattr(local_model, "find_llama_server", lambda: "/bin/llama-server")
    assert asyncio.run(suggest(LocalModel(tmp_path, home=tmp_path), "anything")) is None  # not downloaded


def test_route_parsing_is_strict():
    assert route_request("x" * 10000)["state"].endswith("x" * 10) and len(route_request("x" * 10000)["state"]) < 4100
    assert read_route({"answers": {"tier": {"choice": "galaxy-brain"}}}) is None
    assert read_route({}) is None
    route = read_route({"answers": {"tier": {"choice": "trivial", "confidence": 0.95,
                                             "probabilities": {"trivial": 0.95, "evil": 1}}}})
    assert route == {"tier": "trivial", "confidence": 0.95, "probabilities": {"trivial": 0.95},
                     "suggested_model": "claude-haiku-5-5", "suggested_effort": "low"}


def test_compaction_is_reported_and_the_context_window_is_bounded():
    class SystemMessage:
        subtype = "compact_boundary"
        data = {"compact_metadata": {"trigger": "auto", "pre_tokens": 201000, "post_tokens": 38000}}

    assert map_message(SystemMessage()) == [{"kind": "compaction", "trigger": "auto", "pre_tokens": 201000,
                                             "post_tokens": 38000}]
    assert device_state.context_window({}) == 200_000
    assert device_state.context_window({"context_window": 300_000}) == 300_000
    assert device_state.context_window({"context_window": 900_000}) == 200_000
    assert device_state.context_window({"context_window": "300000"}) == 200_000


@pytest.mark.parametrize("router_on", [True, False])
def test_the_turn_reports_the_suggestion_only_when_the_router_is_on(tmp_path, monkeypatch, router_on):
    from octryx_claude.device_jobs import JobManager
    from octryx_claude.state import LocalState

    state = LocalState(tmp_path)
    device_state.save_device(state, {"device_id": "dev_1", "router": router_on})
    manager = JobManager(state)

    async def fake_suggest(model: Any, prompt: str) -> dict:
        return {"tier": "trivial", "confidence": 0.95, "probabilities": {}, "suggested_model": "claude-haiku-5-5",
                "suggested_effort": "low", "ms": 70}

    monkeypatch.setattr("octryx_claude.router.suggest", fake_suggest)
    events: list[dict] = []

    async def emit(event: dict) -> None:
        events.append(event)

    async def scenario() -> None:
        manager._suggest_route({"prompt": "schreib test.txt", "model": "claude-opus-5-5", "effort": "high"}, emit)
        for _ in range(5):
            await asyncio.sleep(0)

    asyncio.run(scenario())
    if router_on:
        assert events == [{"kind": "route", "tier": "trivial", "confidence": 0.95, "probabilities": {},
                           "suggested_model": "claude-haiku-5-5", "suggested_effort": "low", "ms": 70,
                           "chosen_model": "claude-opus-5-5", "chosen_effort": "high"}]
    else:
        assert events == []



def test_the_default_router_model_is_permissive_and_a_restricted_one_needs_consent_and_the_platform():
    """LFM models (d1-2B) only on explicit choice, never by default."""
    from octryx_claude.local_model import D1_2B, MODELS, ROUTER_MODEL, chosen_model, usable

    assert ROUTER_MODEL.key == "qwen3-1.7b" and ROUTER_MODEL.license["id"] == "Apache-2.0" and ROUTER_MODEL.permissive
    assert D1_2B.license["commercial_restriction"] and not D1_2B.permissive
    assert all({"id", "url", "note", "commercial_restriction", "permissive"} <= set(spec.license)
               for spec in MODELS.values())
    assert chosen_model({}) == ROUTER_MODEL and chosen_model({"router_model": "d1-2b"}) == D1_2B
    assert usable(ROUTER_MODEL, {}, permissive_only=True)
    accepted = {"router_model": "d1-2b", "router_licence_accepted": "LFM-Open-1.0"}
    assert not usable(D1_2B, {"router_model": "d1-2b"}, permissive_only=False)  # no consent
    assert not usable(D1_2B, accepted, permissive_only=True)  # the platform allows only permissive licences
    assert usable(D1_2B, accepted, permissive_only=False)


def test_the_chat_router_reads_the_first_tokens_log_probabilities():
    from octryx_claude.router import chat_request, read_chat_route

    def answer(top):
        candidates = [{"token": token, "logprob": logprob} for token, logprob in top]
        first = {"token": top[0][0], "logprob": top[0][1], "top_logprobs": candidates}
        return {"choices": [{"logprobs": {"content": [first]}}]}

    route = read_chat_route(answer([("tr", -0.1), ("Normal", -2.5), (" hard", -5.0), ("!", -1.0), ("", -0.5)]))
    assert route["tier"] == "trivial" and route["suggested_model"] == "claude-haiku-5-5"
    assert abs(sum(route["probabilities"].values()) - 1) < 0.01
    assert read_chat_route(answer([("hard", -0.2), ("norm", -1.8)]))["tier"] == "hard"
    assert read_chat_route(answer([("yes", -0.1)])) is None and read_chat_route({}) is None
    body = chat_request("  fix it  ")
    assert body["max_tokens"] == 1 and body["logprobs"] is True and body["top_logprobs"] == 20
    assert body["chat_template_kwargs"] == {"enable_thinking": False} and body["messages"][1]["content"] == "fix it"
    assert "--jinja" in server_command("/bin/llama-server", port=1, model_path=Path("m"), chat=True)
    assert "--jinja" not in server_command("/bin/llama-server", port=1, model_path=Path("m"))


@pytest.mark.parametrize(("permissive_only", "reported"), [(True, False), (False, True)])
def test_a_restricted_router_model_runs_only_while_the_platform_allows_it(tmp_path, monkeypatch, permissive_only,
                                                                          reported):
    from octryx_claude.device_jobs import JobManager
    from octryx_claude.state import LocalState

    state = LocalState(tmp_path)
    device_state.save_device(state, {"device_id": "dev_1", "router": True, "router_model": "d1-2b",
                                     "router_licence_accepted": "LFM-Open-1.0"})
    manager = JobManager(state)

    async def fake_suggest(model: Any, prompt: str) -> dict:
        return {"tier": "trivial", "confidence": 0.9, "probabilities": {}, "suggested_model": "claude-haiku-5-5",
                "suggested_effort": "low", "ms": 60}

    monkeypatch.setattr("octryx_claude.router.suggest", fake_suggest)
    events: list[dict] = []

    async def emit(event: dict) -> None:
        events.append(event)

    async def scenario() -> None:
        manager._suggest_route({"prompt": "x", "model": "", "effort": "",
                                "limits": {"local_models_permissive_only": permissive_only}}, emit)
        for _ in range(5):
            await asyncio.sleep(0)

    asyncio.run(scenario())
    assert bool(events) is reported
    assert device_state.load_device(state)["local_models_permissive_only"] is permissive_only
