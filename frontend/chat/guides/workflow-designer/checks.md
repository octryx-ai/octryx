---
title: Checks: "Done when"
order: 5
---

An agent step is done only when its **Done when** checks are met. This keeps an agent from saying "done" too early.

**Adding a check**
1. In the agent step's settings, click **Add a check**.
2. Choose **What is checked**, for example *The last test run passed*.
3. Optionally write it **in your words**; this text is what you see in the list.
4. **Blocks until it is met**: on, the step cannot finish without it. Off, it is only noted and the run goes on.

**Required steps (optional)**
Tools the agent must have used before the step counts as done, for example running the tests. Usually the checks are enough.

**Check box**
A **Check** box on the canvas checks the work of the step before it and ends with *Passed* or *Failed*, so you can draw a way back for *Failed*.

**Good to know**
- Each check shows as one line; click it to change it, **⋯** to remove it.
- A line with a red **!** needs attention.
