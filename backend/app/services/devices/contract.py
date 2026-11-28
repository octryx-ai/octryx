"""The fixed vocabulary of remote device sessions: audience, scopes, limits, states and reason codes."""

from __future__ import annotations

from datetime import timedelta

# The device channel's OAuth audience and scope.
DEVICE_AUDIENCE = "octryx-device"
SCOPE_DEVICE_CONNECT = "device:connect"
# What a device job may do besides connecting: call models through the gateway, the session's MCP tools (reads, and
# writes that each wait for a person's approval in Octryx) and the governed change-workflow tools, exactly the launcher
# login's scopes for them.
DEVICE_JOB_SCOPES = frozenset({"model:invoke", "knowledge:read", "knowledge:write", "workflow:read",
                               "workflow:execute", "sessions:read", "tasks:read", "read"})

# No web-session requirement; 30 days idle (each refresh rotates and extends), 90 days absolute.
DEVICE_GRANT_IDLE_TIMEOUT = timedelta(days=30)
DEVICE_GRANT_ABSOLUTE_LIFETIME = timedelta(days=90)
DEVICE_ACCESS_TOKEN_MINUTES = 15

PROFILE_GOVERNED = "governed"
PROFILE_SEAT = "seat"
PROFILES = (PROFILE_GOVERNED, PROFILE_SEAT)
# The client name the policy engine sees for a device job (seat decision, model picker).
DEVICE_POLICY_CLIENT = "octryx-claude-device"
OS_VALUES = ("macos", "linux", "wsl2")
MIN_PARALLEL_JOBS = 1
MAX_PARALLEL_JOBS = 8
MAX_FOLDERS = 50
MAX_FOLDER_CHARS = 500
MAX_NAME_CHARS = 80

STATE_DENIED = "denied"
STATE_NEEDS_CONFIGURATION = "needs_configuration"
STATE_UNAUTHORIZED = "unauthorized"

REASON_DEVICE_GRANT_REVOKED = "device_grant_revoked"
REASON_DEVICE_GRANT_EXPIRED = "device_grant_expired"
# The platform's device login validity (``login_validity``) ended: ``device enable`` again.
REASON_DEVICE_LOGIN_EXPIRED = "device_login_expired"
REASON_DEVICE_REVOKED = "device_revoked"
REASON_DEVICE_NOT_FOUND = "device_not_found"
REASON_DEVICE_NOT_OWNER = "device_target_not_owner"
REASON_DEVICE_NAME_TAKEN = "device_name_taken"
REASON_DEVICE_NAME_INVALID = "device_name_invalid"
REASON_DEVICE_OS_INVALID = "device_os_invalid"
REASON_DEVICE_KEY_INVALID = "device_public_key_invalid"
REASON_DEVICE_FOLDERS_INVALID = "device_folders_invalid"
REASON_DEVICE_PROFILES_INVALID = "device_profiles_invalid"
REASON_DEVICE_PARALLEL_INVALID = "device_parallel_jobs_invalid"
REASON_FOLDERS_WIDENING = "device_folders_platform_cannot_add"
REASON_LOGIN_REQUIRED = "device_login_required"
REASON_TOKEN_INVALID = "device_token_invalid"
REASON_SCOPE_MISSING = "device_scope_missing"
