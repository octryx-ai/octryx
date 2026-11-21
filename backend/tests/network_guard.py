"""No unit test reaches the real network; imported by conftest.py.

A test that fetches a real remote repository can make a developer's askpass ask for a password, and every such
test waits for a 120 s git timeout. Two layers:

* In-process: ``socket.connect``/``connect_ex``, ``socket.create_connection`` and ``socket.getaddrinfo`` admit only
  this machine (localhost, 127.0.0.0/8, ::1, Unix sockets). Fixture servers on 127.0.0.1 keep working.
* Subprocesses (git, curl, pip): ``HTTP(S)_PROXY`` points to a closed local port and ``NO_PROXY`` names this machine,
  so a request to anywhere else fails at once; git may use only the file, http and https transports (no direct ssh or
  git://), and never prompts.

``OCTRYX_TEST_NETWORK_GUARD``: ``block`` (default) refuses with ``NetworkAccessBlockedError`` and a clear message;
``report`` lets the connection through and records a ``NetworkAccessWarning`` per test (pytest's warnings summary,
also from xdist workers), to find every caller before blocking; ``off`` disables both layers.
"""

from __future__ import annotations

import ipaddress
import os
import socket
import warnings

MODE = os.environ.get("OCTRYX_TEST_NETWORK_GUARD", "block").strip().lower()
LOCAL_NAMES = {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback", ""}
DEAD_PROXY = "http://127.0.0.1:9"  # discard port: nothing listens, the connection is refused at once
SUBPROCESS_ENV = {
    "HTTP_PROXY": DEAD_PROXY, "HTTPS_PROXY": DEAD_PROXY, "http_proxy": DEAD_PROXY, "https_proxy": DEAD_PROXY,
    "ALL_PROXY": DEAD_PROXY, "all_proxy": DEAD_PROXY,
    "NO_PROXY": "localhost,127.0.0.1,::1", "no_proxy": "localhost,127.0.0.1,::1",
    "GIT_ALLOW_PROTOCOL": "file:http:https", "GIT_TERMINAL_PROMPT": "0",
    # boto3 asks the instance metadata service (169.254.169.254) for credentials when a client is built.
    "AWS_EC2_METADATA_DISABLED": "true",
}


class NetworkAccessBlockedError(OSError):
    pass


class NetworkAccessWarning(UserWarning):
    pass


def is_local(host: object) -> bool:
    text = str(host or "").strip().strip("[]").lower()
    if text in LOCAL_NAMES:
        return True
    try:
        address = ipaddress.ip_address(text.split("%", 1)[0])
    except ValueError:
        return False
    return address.is_loopback or address.is_unspecified  # 0.0.0.0 / :: are bind addresses of local servers


def _refuse(host: object, port: object) -> None:
    message = (f"unit tests must not reach the network: {host}:{port}. Use a fixture server on 127.0.0.1, a fake, "
               "or a recorded response (tests/network_guard.py; OCTRYX_TEST_NETWORK_GUARD=report lists every caller)")
    if MODE == "report":
        warnings.warn(NetworkAccessWarning(message), stacklevel=3)
        return
    raise NetworkAccessBlockedError(message)


def _check_address(family: int, address: object) -> None:
    if family == getattr(socket, "AF_UNIX", None) or not isinstance(address, tuple) or not address:
        return
    if not is_local(address[0]):
        _refuse(address[0], address[1] if len(address) > 1 else "")


_original_connect = socket.socket.connect
_original_connect_ex = socket.socket.connect_ex
_original_create_connection = socket.create_connection
_original_getaddrinfo = socket.getaddrinfo


def _connect(self, address):
    _check_address(self.family, address)
    return _original_connect(self, address)


def _connect_ex(self, address):
    _check_address(self.family, address)
    return _original_connect_ex(self, address)


def _create_connection(address, *args, **kwargs):
    if not is_local(address[0]):
        _refuse(address[0], address[1])
    return _original_create_connection(address, *args, **kwargs)


def _getaddrinfo(host, port, *args, **kwargs):
    if host is not None and not is_local(host if not isinstance(host, bytes) else host.decode(errors="replace")):
        _refuse(host, port)
    return _original_getaddrinfo(host, port, *args, **kwargs)


def install() -> None:
    if MODE == "off" or getattr(socket.socket.connect, "__network_guard__", False):
        return
    for function in (_connect, _connect_ex, _create_connection, _getaddrinfo):
        function.__network_guard__ = True
    socket.socket.connect = _connect
    socket.socket.connect_ex = _connect_ex
    socket.create_connection = _create_connection
    socket.getaddrinfo = _getaddrinfo
    os.environ.update(SUBPROCESS_ENV)


install()
