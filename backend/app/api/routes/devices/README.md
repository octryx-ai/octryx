# Device routes

A person's own octryx-claude devices: registration and management, the device channel, device jobs in the chat, the
device-run policy, the host terminal and the public client install endpoints. The rules live in `services/devices`.

## Invariants

- Only a device job's owner reads it, stops it or decides its approvals; anyone else gets `device_job_not_found` or
  `device_approval_not_owner` (`services/devices/job_state.py`).
- The host terminal is served only when `OCTRYX_ENABLE_HOST_TERMINAL` is on, and only to an active global admin's
  own login, never an API key (`terminal.get_interactive_admin`, `runtime_toggles.host_terminal_enabled`).
