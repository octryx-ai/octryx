"""Each hands-on pass serves the app on a free port when the serve command names the declared one.

Parallel runs on the file's fixed port would wait for each other, and a server left on that port makes the test
refuse "something else already answers".
"""

from __future__ import annotations

import socket

from octryx_claude.serve_port import free_port, on_free_port

FLUTTER = {"command": "flutter build web --release && python3 -m http.server 8090 --bind 127.0.0.1 --directory "
                      "build/web", "url": "http://127.0.0.1:8090/", "ready_seconds": 600}


def test_a_command_that_names_its_port_moves_to_a_free_one_with_its_url_and_port_env():
    serve, env = on_free_port(FLUTTER, {"HOME": "/h"}, pick=lambda: 51234)
    assert serve["command"].endswith("http.server 51234 --bind 127.0.0.1 --directory build/web")
    assert (serve["url"], serve["declared_url"], serve["ready_seconds"]) == (
        "http://127.0.0.1:51234/", "http://127.0.0.1:8090/", 600)
    assert env == {"HOME": "/h", "PORT": "51234"}


def test_a_command_without_the_port_keeps_the_declared_url():
    npm = {"command": "npm run preview", "url": "http://127.0.0.1:4173/"}
    assert on_free_port(npm, {}, pick=lambda: 1) == (npm, {})
    longer = {"command": "serve --port 80901", "url": "http://127.0.0.1:8090/"}  # 8090 inside another number
    assert on_free_port(longer, {}, pick=lambda: 1) == (longer, {})


def test_the_free_port_is_bindable_on_loopback():
    port = free_port()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", port))
