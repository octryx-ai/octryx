---
title: Actions
---

An action is a reusable piece of automated work that runs without a chat.

### What you do here
- Create an action: the Workspace, the agent it runs and its prompt.
- Run it now with **Execute**, or let a scheduler or webhook start it.
- Open an action's row to see its steps, dependencies and run history in the side panel; **Execute**, edit and pause sit at its top, **Delete** is in its ⋯ menu.

### Next steps
- [Open schedulers](/chat?area=admin&tab=schedulers)
- [Open webhooks](/chat?area=admin&tab=webhooks)

### Actions, schedulers and workflows
- An **action** is a reusable piece of automated work: which agent or mode runs, with which dependencies and ordered steps. Every run keeps its status and history.
- It runs when you start it here, or on a timetable through a **scheduler**, which only decides when.
- A **workflow** is different: it shapes how the agent handles a chat turn when someone selects it, while an action runs without a chat.
- A new action is created active, without a schedule of its own. Creating it does not start a run; a scheduler or Execute does.
- The table's **Started by** names what starts the action (hover it for every start), **Type** is the kind of action (an agent run, or a Jira or ServiceNow intake sync), **State** is **Active**, **Running** (a run is going) or **Paused**, and **Last run** is the latest run's status and date.
- Example: a "Nightly Jira triage" action runs an agent with one step that summarises new tickets; a scheduler then runs it every night.
