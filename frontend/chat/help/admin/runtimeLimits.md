---
title: Budgets
---

Every limit and budget of the platform in one place.

### What you do here
- Set the platform value of each limit; open a count of Workspace overrides to see them.
- Add a budget period for a Workspace or a person.
- Choose what a cost cap does with a model that has no price, and the ceiling for workflow run loops.

### Next steps
- [Review model prices in the catalog](/chat?area=admin&tab=modelCatalog)
- [Set the platform order](/chat?area=admin&tab=modelOrder)

### Limits
- An empty Workspace value inherits the platform value; it never means "no limit". Use "No limit" explicitly.
- Without a budget period, the cost caps per session and request still apply.

### Budget periods
- A budget counts the cost of every model call in its scope during the period. At "stop at", further calls are refused with a visible reason.
- A budget is turned off, never deleted, so its history stays readable.

### Models without a price
- This decides what a cost cap does with a platform-billed model that has no price.
- Seat, device and governed gateway models are not affected.

### Workflow run loops
- The ceiling is the highest number of iterations any loop of a workflow run may have.
- Reaching a loop's limit pauses the run until its requester continues, changes the plan or aborts.
