---
title: Webhooks
---

Inbound webhooks let a monitoring tool start an analysis; outbound webhooks send platform events to your URL.

### What you do here
- Create an inbound webhook: the tool that sends the alerts, the Workspace and the action it starts.
- Paste its URL and secret into the sending tool, then send a test alert.
- Create an outbound webhook: your URL and the events it receives.
- Read the latest alerts and the outbound deliveries.

### Next steps
- [Open actions](/chat?area=admin&tab=tasks)
- [Open channels](/chat?area=admin&tab=channels)

### Inbound: how an alert starts an analysis
A monitoring tool posts an alert to a webhook. The platform checks the signature, groups repeats, and starts the chosen action in its Workspace; the result goes where the action sends it.

1. **Alert arrives**: Alertmanager, Grafana, Datadog, any JSON.
2. **Signature checked**: repeats grouped, limits applied.
3. **Analysis starts**: the action runs in the Workspace.
4. **Result delivered**: to a channel or the run history.

Each webhook is one row in the table. **State** is **Active**, **Needs setup** (hover it for what is missing) or **Paused**; **Last alert** shows this week's count as its tooltip. Open a row for the URL, the secret, a test alert, the recent alerts and the setup. **Pause**/**Resume** is at the bottom of its panel; **Remove…** is in the ⋯ menu of the row and of the panel.

The latest alerts of all webhooks are listed below the table. **Outcome** reads in words: **Started** and **Analysis finished** mean an analysis ran; **Grouped** means the alert was a repeat of an earlier one; **Skipped** means a filter or limit applied; **Waiting** means the webhook needs setup; **Rejected** means the signature did not match; **Duplicate** means the same call arrived again inside the replay window, so nothing started.

**Accept calls without a signed timestamp** (in an inbound webhook's panel) is for tools that can only send the secret or sign the body. Repeats of the same call within 5 minutes are still refused.

New webhooks start with safe defaults: critical and warning alerts only, repeats grouped within 30 minutes, at most 20 analyses per hour. Change them in the webhook after creating it.

### Outbound
An outbound webhook is your URL that the platform calls, signed, when one of the selected events happens. Every attempt is listed under Outbound deliveries; deliveries appear once an outbound webhook is triggered by one of its events. The signing secret is shown once, when the webhook is created.

Open a row to edit an outbound webhook; **Enable**/**Disable** and **Delete** are in the row's ⋯ menu. **Last delivery** shows the latest attempt's status, with its error as the tooltip.
