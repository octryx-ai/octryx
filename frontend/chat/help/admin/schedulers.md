---
title: Schedulers
---

A scheduler starts an action at fixed times.

### What you do here
- Create a scheduler: choose the action it runs and when it runs. Creating activates it.
- Pause, resume or edit a scheduler, or delete it from its row menu.
- Check the worker status to see whether the scheduling worker registered the current version.

### Next steps
- [Open actions](/chat?area=admin&tab=tasks)
- [Open webhooks](/chat?area=admin&tab=webhooks)

### How schedulers work
- A scheduler decides **when**; its linked action decides **what** runs.
- Pausing or deleting a scheduler stops it adding new runs to the queue; runs already queued or running are not cancelled.
- Worker status shows whether the scheduling worker registered the current version, not whether a run succeeded.
- The worker status shows the state as of when the list was loaded or last checked. It is not updated live; use **Check worker status** to refresh it.
- Schedules managed by Work → Intake or set on the action are edited where they are managed. Here they can be paused, resumed and deleted. A schedule set on the action follows the action's own switch: **Pause action** pauses the action, and **Remove schedule…** clears only its schedule.

### The table
- **Starts** is the action and its Workspace; **Runs** is the schedule in words (the expression is its tooltip).
- **State** is **Paused** for a paused scheduler; for an active one it is the worker status: **Applied by the worker**, **Waiting for the worker**, **No scheduling worker**, **Schedule not usable** or **Status not available**. Hover it for the reason.
- Open a row for the details, the last run and the full worker status. **Edit** changes it, **Pause**/**Resume** switches it, and **Delete** is in the ⋯ menu.
