"""A scripted ``codex app-server`` for the driver tests."""

from __future__ import annotations

import json
import stat
import sys
from pathlib import Path
from typing import Any

_SERVER = r'''
import hashlib, json, os, re, sys, tomllib, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
scenario = json.load(open(os.path.join(HERE, "scenario.json")))
if sys.argv[1:] == ["--version"]:
    print(scenario.get("version", "codex-cli 0.169.0"))
    sys.exit(0)
home = os.environ.get("CODEX_HOME", "")
config_path = os.path.realpath(os.path.join(home, "config.toml"))
log = open(os.path.join(HERE, "calls.jsonl"), "a")
json.dump({"argv": sys.argv[1:], "home": home, "key": os.environ.get("OPENAI_API_KEY")},
          open(os.path.join(HERE, "argv.json"), "w"))
turns = list(scenario.get("turns") or [])
ids = iter(range(1000, 100000))
thread = scenario.get("thread", "th-1")
overrides = {}
turn_count = 0


def send(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def receive():
    line = sys.stdin.readline()
    if not line:
        sys.exit(0)
    message = json.loads(line)
    log.write(json.dumps(message) + "\n")
    log.flush()
    return message


def user_config():
    return tomllib.load(open(config_path, "rb"))


def repo_layer(cwd):
    path = os.path.join(cwd, ".codex", "config.toml")
    if not os.path.exists(path):
        return None
    trust = (user_config().get("projects") or {}).get(os.path.realpath(cwd), {}).get("trust_level")
    disabled = trust == "untrusted" and not scenario.get("ignore_untrust")
    return {"config": tomllib.load(open(path, "rb")), "disabled": disabled, "path": os.path.dirname(path)}


def effective(cwd):
    config = user_config()
    layer = repo_layer(cwd)
    if layer and not layer["disabled"]:
        for key, value in layer["config"].items():
            if isinstance(value, dict) and isinstance(config.get(key), dict):
                merged = dict(config[key])
                for name, inner in value.items():
                    merged[name] = {**merged.get(name, {}), **inner} if isinstance(inner, dict) else inner
                config[key] = merged
            else:
                config[key] = value
    return config


def declaration_hash(label, handler):
    identity = {"event_name": label, "hooks": [{**handler, "async": False}]}
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def hooks(cwd):
    mode = scenario.get("hooks", "trustable")
    if mode == "none":
        return []
    config = user_config()
    state = (config.get("hooks") or {}).get("state", {})
    listed = []
    for event, groups in (config.get("hooks") or {}).items():
        if event == "state":
            continue
        label = re.sub(r"(?<!^)(?=[A-Z])", "_", event).lower()
        handler = dict(groups[0]["hooks"][0])
        key = f"{config_path}:{label}:0:0"
        current = declaration_hash(label, handler)
        pinned = (state.get(key) or {}).get("trusted_hash")
        trusted = mode != "untrustable" and pinned == current
        listed.append({"key": key, "eventName": event[0].lower() + event[1:], "command": handler["command"],
                       "timeoutSec": handler.get("timeout"), "matcher": None, "handlerType": "command",
                       "source": "user", "isManaged": False, "sourcePath": config_path,
                       "enabled": mode != f"disabled:{label}", "currentHash": current,
                       "trustStatus": "trusted" if trusted else ("modified" if pinned else "untrusted")})
    listed = [hook for hook in listed if mode != f"drop:{hook['key'].split(':')[-3]}"]
    if mode == "extra":
        listed.append({**listed[0], "key": f"{cwd}/.codex/config.toml:pre_tool_use:0:0", "source": "project"})
    return listed


def servers(cwd, name=None):
    configured = effective(cwd).get("mcp_servers") or {}
    rows = []
    for server, spec in configured.items():
        enabled = overrides.get(f"mcp_servers.{server}.enabled", spec.get("enabled", True))
        row = {"name": server, "runtimeStatus": "connected" if enabled else "disabled", "tools": {},
               "httpOrigin": scenario.get("origin") or "/".join(str(spec.get("url", "")).split("/")[:3]) or None}
        if enabled and server == "octryx_knowledge":
            if scenario.get("tools", True):
                row["tools"] = {"knowledge_search": {}}
            else:
                row.update(runtimeStatus="failed", toolsError=scenario.get("tools_error", "failed"))
        rows.append(row)
    return [row for row in rows if name in (None, row["name"])]


def call_provider():
    provider = tomllib.load(open(config_path, "rb"))["model_providers"]["octryx_seat"]
    headers = {name: os.environ[env] for name, env in provider["env_http_headers"].items()}
    headers.update(provider["http_headers"], authorization="Bearer chatgpt")
    headers["content-type"] = "application/json"
    request = urllib.request.Request(provider["base_url"] + "/responses", data=b'{"model": "m"}', headers=headers,
                                     method="POST")
    status = urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=10).status
    json.dump({"status": status, "url": provider["base_url"]}, open(os.path.join(HERE, "seen.json"), "w"))


def capture_stop(turn_id):
    # What the launcher's Stop hook remembers when Codex ends a turn (hooks._defer_stop).
    root, key = os.environ.get("OCTRYX_CLAUDE_HOME"), os.environ.get("OCTRYX_SESSION_KEY")
    if not root or not key or not scenario.get("stop_capture", True):
        return
    folder = os.path.join(root, "sessions", key)
    os.makedirs(folder, exist_ok=True)
    captured = {"hook_event_name": "Stop", "session_id": scenario.get("stop_thread", thread), "turn_id": turn_id}
    json.dump(captured, open(os.path.join(folder, scenario["stop_file"]), "w"))


def complete(turn_id, status, error=None):
    if status == "completed":
        capture_stop(turn_id)
    turn = {"id": turn_id, "status": status}
    if error:
        turn["error"] = error
    send({"jsonrpc": "2.0", "method": "turn/completed", "params": {"threadId": thread, "turn": turn}})


def run_turn(turn_id, steps):
    status, error = "completed", None
    for step in steps:
        if "notify" in step:
            params = dict(step.get("params") or {})
            params.setdefault("threadId", thread)
            params.setdefault("turnId", turn_id)
            send({"jsonrpc": "2.0", "method": step["notify"], "params": params})
        elif "request" in step:
            request_id = next(ids)
            send({"jsonrpc": "2.0", "id": request_id, "method": step["request"], "params": step.get("params") or {}})
            while receive().get("id") != request_id:
                pass
        elif step.get("hang"):
            while True:
                message = receive()
                if message.get("method") == "turn/interrupt":
                    send({"jsonrpc": "2.0", "id": message["id"], "result": {}})
                    complete(turn_id, "interrupted")
                    return
        elif step.get("call_provider"):
            call_provider()
        elif step.get("exit"):
            sys.exit(3)
        elif "status" in step:
            status, error = step["status"], step.get("error")
    complete(turn_id, status, error)


cwd = os.getcwd()
sandbox_types = {"workspace-write": "workspaceWrite", "danger-full-access": "dangerFullAccess"}
while True:
    message = receive()
    method, request_id = message.get("method"), message.get("id")
    params = message.get("params") or {}
    if request_id is None:
        continue
    if method == scenario.get("exit_on"):
        sys.exit(4)
    if method == "initialize":
        result = {"userAgent": "fake"}
    elif method == "hooks/list":
        where = (params.get("cwds") or [cwd])[0]
        result = {"data": [{"cwd": where, "hooks": hooks(where),
                            "errors": scenario.get("hook_errors", []), "warnings": []}]}
    elif method == "config/read":
        layer = repo_layer(params["cwd"])
        layers = [{"name": {"type": "user", "file": config_path}, "config": {}, "version": "1",
                   "disabledReason": None}]
        hidden = scenario.get("hide_layer")
        if layer:
            disabled = layer["disabled"] or hidden
            layers.insert(0, {"name": {"type": "project", "dotCodexFolder": layer["path"]}, "config": layer["config"],
                              "version": "1", "disabledReason": "untrusted" if disabled else None})
        result = {"config": user_config() if hidden else effective(params["cwd"]), "layers": layers, "origins": {}}
    elif method in ("thread/start", "thread/resume"):
        thread = params.get("threadId") or thread
        overrides = params.get("config") or {}
        config = effective(cwd)
        result = {"thread": {"id": thread},
                  "approvalPolicy": scenario.get("thread_approval") or params.get("approvalPolicy")
                  or config.get("approval_policy"),
                  "approvalsReviewer": params.get("approvalsReviewer", "user"),
                  "sandbox": {"type": sandbox_types.get(params.get("sandbox") or config.get("sandbox_mode"))}}
    elif method == "mcpServerStatus/list":
        result = {"data": servers(cwd, params.get("serverName"))}
    elif method == "turn/start":
        turn_count += 1
        send({"jsonrpc": "2.0", "id": request_id, "result": {"turn": {"id": f"turn-{turn_count}"}}})
        run_turn(f"turn-{turn_count}", turns.pop(0) if turns else [])
        continue
    elif method == "thread/compact/start":
        turn_count += 1
        send({"jsonrpc": "2.0", "id": request_id, "result": {}})
        run_turn(f"turn-{turn_count}", turns.pop(0) if turns else [])
        continue
    elif method == "turn/interrupt":
        result = {}
    else:
        send({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": method}})
        continue
    send({"jsonrpc": "2.0", "id": request_id, "result": result})
'''


def fake_appserver(folder: Path, **scenario: Any) -> Path:
    from octryx_claude.hooks import DEFERRED_STOP_FILE

    scenario.setdefault("stop_file", DEFERRED_STOP_FILE)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "scenario.json").write_text(json.dumps(scenario))
    script = folder / "codex"
    script.write_text(f"#!{sys.executable}\n{_SERVER}")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def calls(folder: Path) -> list[dict[str, Any]]:
    path = folder / "calls.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
