# Channel routes

Inbound channels: chat-platform webhooks (Teams, Slack), alert webhooks that start an Action, speech-to-text and the
Teams call audio bridge.

## Invariants

- A channel webhook is authenticated by its channel's own scheme (Teams: Microsoft JWT; Slack: request signature)
  before its body is parsed; a channel type without a scheme is refused. The one exception is the development bypass
  setting, honoured only in a development environment (`services/channel_webhook_auth/gate.py`,
  `channel_webhook_dev_policy.py`).
- A Workspace's speech-to-text configuration is used only for a member of that Workspace or an admin; another
  Workspace answers 404 before any audio is sent (`stt.py`, `services/access_control.require_visible_workspace`).
