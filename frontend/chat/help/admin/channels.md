---
title: Channels
---

Channels such as Microsoft Teams or Slack, where people reach agents and where events are posted.

### What you do here
- Add a channel from the catalog, fill in its configuration and enable it.
- Enable, reload or remove a channel; each channel is enabled on its own.
- Add Teams delivery targets: where a Workspace's events are posted.
- Under **Problem alerts**, send a Workspace's run and device problems by email, Slack or Microsoft Teams.
- Set up voice calls, and read outbound messages and channel sessions.

### Next steps
- [Open webhooks](/chat?area=admin&tab=webhooks)
- [Open schedulers](/chat?area=admin&tab=schedulers)

### Overview
Delivery channels carry inbound and outbound agent communication. Each channel can be enabled independently and reloaded after configuration changes.

The table lists every configured channel. **State** reads:
- **Running**: the channel is enabled and its worker is connected.
- **Enabled**: the channel is allowed to send and receive, but its worker is not running (yet); reload it after a configuration change.
- **Off**: the channel is disabled and neither sends nor receives.

Open a row for the channel's details. **Configure** edits its settings; **Enable**/**Disable** and **Reload** sit beside it, and **Remove** is in the ⋯ menu.

### Teams delivery targets
Where Workspace events such as approval requests and trace alerts are posted in Microsoft Teams. A delivery target needs a configured Microsoft Teams channel.

### Problem alerts
Where a Workspace's run and device problems (stuck, looping or failed runs, stalled device jobs) are sent: an email address, a Slack channel or member ID, or a Teams conversation. Each row is one Workspace and one channel. **Through** is the channel connection that sends it; with "Any active … channel" the first enabled one is used. **Needs configuration** means no enabled channel of that kind can send it yet: add one under Overview.

Each problem is sent once. When many problems appear at the same time, a Workspace gets the first ones one by one and then one summary ("N more problems") that links to the Workspace's Work page.

**Send test** in a row's ⋯ menu queues a test message to its target. The Workspace's admins also get every problem in the app, and the run's own people get theirs. Webhooks receive `problem.raised` and `problem.cleared` as well; set them up under [Webhooks](/chat?area=admin&tab=webhooks).

### Outbound messages
Delivery status for messages sent through configured channels. Failed and retrying rows show the latest delivery error. Messages appear once a delivery target receives an event.
- **Sent**: delivered successfully.
- **Pending** or **Retrying**: waiting for delivery or for the next attempt.
- **Failed**, or **Failed, no more retries**: the delivery did not succeed; the error column says why.

### Channel sessions
Recent sessions created from external channels; a session starts when someone writes to the agent through a configured channel. This view is available only in Admin and does not change normal user thread access. Teams call sessions appear when someone calls the agent in Microsoft Teams.
