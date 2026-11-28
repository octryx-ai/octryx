#!/bin/sh
# Starts as root only to hand the writable places to their owners, then runs the launcher as `octryx` with nothing
# but the right to start Codex under the agent's account.
set -eu
# A Kubernetes emptyDir comes without the sticky bit: no account may move another's folder out of /tmp.
chmod 1777 /tmp
install -d -o octryx -g agent -m 3770 /var/lib/octryx
install -d -o octryx -g agent -m 2770 /workspace
install -d -o agent -g agent -m 0700 /tmp/agent-home
install -d -o octryx -g octryx -m 0700 /tmp/home
export OCTRYX_AGENT_UID=10002 OCTRYX_SHARED_STATE=1
umask 007
exec setpriv --reuid=octryx --regid=octryx --init-groups \
  --inh-caps=-all,+setuid,+setgid --ambient-caps=-all,+setuid,+setgid --bounding-set=-all,+setuid,+setgid \
  python -I -c 'import sys; sys.path.insert(0, "/opt/octryx/lib"); from octryx_claude.entry import main; sys.exit(main())' \
  device run --runner
