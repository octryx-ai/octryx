---
title: Defaults
---

The default model, what happens when a model fails, and the model of each background task.

### What you do here
- **Platform order**: sort the models; #1 is the platform default and the same order is the fallback order.
- Choose what happens when a model fails: try the next allowed model, or stop with an error.
- **Task models**: give a background task its own model from the platform order.
- **Explain a turn**: see which model a turn would use, and why.

### Next steps
- [Review the model catalog](/chat?area=admin&tab=modelCatalog)
- [Set budgets and limits](/chat?area=admin&tab=runtimeLimits)

### The platform order
- When nobody chose a model, the first model in this order that the Workspace allows and has cleared for its data runs.
- The order and the fallback apply to chat, agents, scheduled runs and workflows. Fallback never leaves the Workspace's allowed models or the data clearance.

### Task models
- Background tasks are work that is not a conversation. Each uses the platform default unless a model from the platform order is set.
- A Workspace can override a task in its Models section.
- The lists other features read (diagram types, workflow proposal settings) are under **Open policy lists**.

### Explain a turn
- One resolver decides for chat, sub-agents, scheduled runs, workflows, task models and the model gateway.
- A model the person picks that is not allowed is refused with the reason. It is never swapped silently.
