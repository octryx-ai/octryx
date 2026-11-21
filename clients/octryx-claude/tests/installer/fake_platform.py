"""Fake Octryx platform for the installer tests (stdlib + the platform's own builder).

Serves the installer scripts and the package through the platform's real code
(``backend/app/services/octryx_client``: renderer and wheel builder), built from ``CLIENT_DIR`` so a
test can change the sources and get a new version. Records ``/oauth/revoke`` calls.

    python fake_platform.py PORT STATE_DIR CLIENT_DIR SCRIPTS_DIR

``STATE_DIR/tamper`` present: the package bytes are altered (checksum mismatch).
``STATE_DIR/nopackage`` present: the package download answers 404.
"""

import json
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "backend" / "app" / "services"))

from octryx_client import artifact, installers  # noqa: E402

PORT = int(sys.argv[1])
STATE = Path(sys.argv[2])
CLIENT_DIR = Path(sys.argv[3])
SCRIPTS_DIR = Path(sys.argv[4])
BASE_URL = f"http://127.0.0.1:{PORT}"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, body, content_type="application/json", code=200):
        data = body if isinstance(body, bytes) else json.dumps(body, separators=(",", ":")).encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(url.query)
        workspace = query.get("workspace", [""])[0]
        name = url.path.removeprefix("/octryx-claude/")
        if name in installers.SCRIPTS:
            template = installers.installer_template(name, CLIENT_DIR)
            script = installers.render(template, base_url=BASE_URL, workspace=workspace,
                                         os_junk=installers.os_junk_files(CLIENT_DIR))
            return self.send(script.encode(), "text/plain; charset=utf-8")
        built = artifact.build_artifact(CLIENT_DIR, SCRIPTS_DIR)
        if name == "version":
            return self.send({"client": "octryx-claude", "version": built.version, "filename": built.filename,
                              "sha256": built.sha256, "requires_python": built.requires_python,
                              "install": installers.install_commands(BASE_URL, workspace)})
        if name == f"package/{built.version}" and not (STATE / "nopackage").exists():
            content = built.content
            if (STATE / "tamper").exists():
                content = content[:-1] + bytes([content[-1] ^ 0xFF])
            return self.send(content, "application/octet-stream")
        self.send({"state": "denied", "reason": "not_found"}, code=404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        form = urllib.parse.parse_qs(self.rfile.read(length).decode())
        if self.path == "/oauth/revoke":
            with (STATE / "revoked").open("a") as handle:
                handle.write(form.get("token", [""])[0] + "\n")
            return self.send({"ok": True})
        self.send({"error": "not_found"}, code=404)


ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
