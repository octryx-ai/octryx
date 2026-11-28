from __future__ import annotations

import asyncio
import stat
import sys

import pytest

from octryx_claude import codex_appserver
from octryx_claude.codex_appserver import EXITED, AppServerClient, AppServerError


def _server(tmp_path, body: str):
    script = tmp_path / "server"
    script.write_text(f"#!{sys.executable}\nimport json, sys\n{body}")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


async def _no_requests(_method, _params):
    return {}


def _client(tmp_path, body):
    return AppServerClient([_server(tmp_path, body)], env={"PATH": "/usr/bin:/bin"}, cwd=str(tmp_path),
                           on_request=_no_requests)


ANSWER_INITIALIZE = """
line = sys.stdin.readline()
print(json.dumps({"jsonrpc": "2.0", "id": json.loads(line)["id"], "result": {}}), flush=True)
sys.stdin.readline()
"""


def test_an_oversized_line_fails_the_pending_request_and_wakes_the_turn(tmp_path, monkeypatch):
    monkeypatch.setattr(codex_appserver, "STREAM_LIMIT", 1024)
    client = _client(tmp_path, ANSWER_INITIALIZE + """
sys.stdin.readline()
print("x" * 4096, flush=True)
sys.stdin.read()
""")

    async def scenario():
        await client.start()
        with pytest.raises(AppServerError) as failed:
            await client.request("thread/start", {}, timeout=5)
        notice = await asyncio.wait_for(client.next_notification(), 5)
        await client.close()
        return failed.value.code, notice

    code, notice = asyncio.run(scenario())
    assert code == "closed" and notice == {"method": EXITED}


def test_replies_that_are_not_json_rpc_are_ignored_until_the_deadline(tmp_path):
    client = _client(tmp_path, ANSWER_INITIALIZE + """
line = json.loads(sys.stdin.readline())
print(json.dumps([1, 2]), flush=True)
print(json.dumps({"id": line["id"], "params": "not an object"}), flush=True)
sys.stdin.read()
""")

    async def scenario():
        await client.start()
        with pytest.raises(AppServerError) as failed:
            await client.request("thread/start", {}, timeout=0.5)
        await client.close()
        return failed.value.code

    assert asyncio.run(scenario()) == "timeout"


def test_an_rpc_error_keeps_only_its_code(tmp_path):
    client = _client(tmp_path, ANSWER_INITIALIZE + """
line = json.loads(sys.stdin.readline())
print(json.dumps({"jsonrpc": "2.0", "id": line["id"], "error": {"code": -32000, "message": "token=secret-value"}}),
      flush=True)
sys.stdin.read()
""")

    async def scenario():
        await client.start()
        with pytest.raises(AppServerError) as failed:
            await client.request("thread/start", {})
        await client.close()
        return failed.value

    error = asyncio.run(scenario())
    assert error.code == "rpc_-32000" and "secret-value" not in str(error)


@pytest.mark.parametrize("code", ['"token=secret-value"', "1.5", "true"])
def test_an_rpc_error_code_that_is_not_an_integer_is_not_repeated(tmp_path, code):
    client = _client(tmp_path, ANSWER_INITIALIZE + f"""
line = json.loads(sys.stdin.readline())
sys.stdout.write('{{"jsonrpc": "2.0", "id": ' + str(line["id"]) + ', "error": {{"code": {code}}}}}' + "\\n")
sys.stdout.flush()
sys.stdin.read()
""")

    async def scenario():
        await client.start()
        with pytest.raises(AppServerError) as failed:
            await client.request("thread/start", {})
        await client.close()
        return failed.value

    error = asyncio.run(scenario())
    assert error.code == "rpc_invalid" and "secret" not in str(error)


def test_too_many_notifications_close_the_transport_instead_of_blocking(tmp_path, monkeypatch):
    monkeypatch.setattr(codex_appserver, "MAX_NOTIFICATIONS", 5)
    client = _client(tmp_path, ANSWER_INITIALIZE + """
line = json.loads(sys.stdin.readline())
for index in range(50):
    print(json.dumps({"jsonrpc": "2.0", "method": "item/started", "params": {}}), flush=True)
print(json.dumps({"jsonrpc": "2.0", "id": line["id"], "result": {}}), flush=True)
sys.stdin.read()
""")

    async def scenario():
        await client.start()
        with pytest.raises(AppServerError) as failed:
            await client.request("thread/start", {}, timeout=5)
        await client.close()
        return failed.value.code

    assert asyncio.run(scenario()) == "closed"


def test_a_failed_transport_is_reported_before_the_backlog(tmp_path, monkeypatch):
    monkeypatch.setattr(codex_appserver, "MAX_NOTIFICATION_BYTES", 2000)
    client = _client(tmp_path, ANSWER_INITIALIZE + """
for index in range(10):
    print(json.dumps({"jsonrpc": "2.0", "method": "item/started", "params": {"pad": "x" * 500}}), flush=True)
sys.stdin.read()
""")

    async def scenario():
        await client.start()

        async def closed():
            while client.running:
                await asyncio.sleep(0.01)

        await asyncio.wait_for(closed(), 5)
        notice = await asyncio.wait_for(client.next_notification(), 5)
        await client.close()
        return notice

    assert asyncio.run(scenario()) == {"method": EXITED}


def test_an_ordinary_end_delivers_what_came_before_it(tmp_path):
    client = _client(tmp_path, ANSWER_INITIALIZE + """
print(json.dumps({"jsonrpc": "2.0", "method": "turn/completed", "params": {}}), flush=True)
""")

    async def scenario():
        await client.start()
        first = await asyncio.wait_for(client.next_notification(), 5)
        second = await asyncio.wait_for(client.next_notification(), 5)
        await client.close()
        return first["method"], second["method"]

    assert asyncio.run(scenario()) == ("turn/completed", EXITED)
