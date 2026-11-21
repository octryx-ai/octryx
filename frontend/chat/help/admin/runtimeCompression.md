---
title: Tool output compression
---

Large tool results are shrunk before they are sent back to the model.

### What you do here
- See which tools compress their results and by how much.
- Tune a tool's limits.
- Turn compression off for a tool while troubleshooting.

### Next steps
- [Review execution & storage](/chat?area=admin&tab=runtimeExecution)
- [Set budgets](/chat?area=admin&tab=runtimeLimits)

### Good to know
- Each tool has a fixed compression profile.
- Reduction is the share of tokens removed before a tool result reached the model. 0 % means nothing was removed: the result was passed through at full size.
