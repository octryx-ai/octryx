"""``octryx-claude profiles``: list, connect and disconnect the Claude Code profiles outside octryx.
Nothing of a profile is read before it is connected."""

from __future__ import annotations

import argparse
import sys

from . import local_profiles
from .state import LocalState


def add_parser(sub: argparse._SubParsersAction) -> None:
    profiles = sub.add_parser("profiles", help="Claude Code profiles outside octryx: show, connect, disconnect")
    actions = profiles.add_subparsers(dest="profiles_command")
    connect = actions.add_parser("connect", help="show this profile's sessions in your private Workspace")
    connect.add_argument("path", help="the profile's folder, e.g. ~/.claude or ~/.claude-private")
    connect.add_argument("--name", default="", help="a short name (1-8 characters), e.g. team or private")
    connect.add_argument("--allow-takeover", action="store_true",
                         help="also let your phone RUN Claude Code in this profile on this Mac (remote execution)")
    disconnect = actions.add_parser("disconnect", help="stop showing this profile's sessions")
    disconnect.add_argument("name")


def run_profiles_command(args: argparse.Namespace, state: LocalState) -> int:
    command = getattr(args, "profiles_command", None)
    if command == "connect":
        try:
            profile = local_profiles.connect(state, args.path, name=args.name, allow_takeover=args.allow_takeover)
        except local_profiles.ProfileError as exc:
            print(f"octryx-claude: {exc}", file=sys.stderr)
            return 2
        print(f"Connected {profile.name}: {profile.config_dir}")
        print("Its recent sessions appear in your private Workspace and on your phone within a minute.")
        if profile.allow_takeover:
            print("Take over is ON: from your phone you can run Claude Code in this profile on this Mac, in the")
            print("session's folder and with this profile's own login. Every write needs your approval on the phone,")
            print("and this Mac shows a notification for each remote turn. Turn it off with")
            print(f"`octryx-claude profiles connect {profile.config_dir} --name {profile.name}`"
                  " (without --allow-takeover).")
        else:
            print("Take over is off: the phone shows these sessions but cannot run anything here.")
        return 0
    if command == "disconnect":
        if local_profiles.disconnect(state, args.name):
            print(f"Disconnected {args.name}.")
            return 0
        print(f"octryx-claude: no connected profile named {args.name!r}", file=sys.stderr)
        return 2
    connected = {profile.config_dir: profile.name for profile in local_profiles.connected(state)}
    found = local_profiles.discover(state)
    if not found and not connected:
        print("No Claude Code profiles found besides octryx's own.")
        return 0
    print("Claude Code profiles on this machine:")
    for path in [*found, *[path for path in connected if path not in found]]:
        name = connected.get(path)
        status = f"connected as {name}" if name else (
            f"not connected  (octryx-claude profiles connect {path} --name {local_profiles.suggested_name(path)})")
        print(f"  {path}  {status}")
    return 0


__all__ = ["add_parser", "run_profiles_command"]
