---
title: Agents · Build
---

Define agents, their prompts and the workflows they run.

### What you do here
- Build and test agents and workflows.
- Publish a tested draft.
- Review check results after each turn.

### Next steps
- [Review agents](/chat?area=workflows&tab=agents)
- [Open the workflows](/chat?area=workflows&tab=workflowList)
- [Review check results](/chat?area=workflows&tab=workflowChecks)

### Good to know
- New to the workflow designer? Read the [Workflow designer guide](guide:workflow-designer/index): reading, building from scratch, conditions, approvals, checks, publishing.
- Published revisions cannot be changed; publishing governed changes may need a second approver.
- New agents start without broad permissions or a preselected Workspace.
- In a workflow's Canvas, **+ Step** and **+ Check** open a side panel; the workflow changes only with **Add step** or **Add check**. A click on a step or check opens its settings; **Move earlier**, **Move later** and **Remove** (⋯) are there.
- A **strict** step: the turn cannot finish until the tool ran (two reminders, then not verified; octryx-claude's Stop blocks). A **guided** step: one reminder, then the turn continues.
