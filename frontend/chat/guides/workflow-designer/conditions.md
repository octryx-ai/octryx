---
title: Conditions and branches
order: 3
---

A **Condition** sends the run one way or another. It looks at one of two things.

**The result of a step**
1. Under **Looks at**, choose *The result of a step*, then the step.
2. Under **Where the run goes**, choose for each result the box that comes next, for example *Passed → Push*, *Failed → Minimal fix*.
3. **Otherwise** catches every result without its own box. A result set to *Like otherwise* goes there too.

An agent step has results only if you give it **Possible results**, for example *Fix needed* and *No fix*. You find them in the agent step's settings.

**A field of the ticket**
1. Under **Looks at**, choose *A field of the ticket*.
2. Choose the field, how to compare and the value, for example *Priority is High*.
3. Choose where the run goes for **Yes** and for **Otherwise**.

**Good to know**
- Every possible result needs a way: its own box or **Otherwise**. Otherwise the workflow cannot be published.
- Several conditions combined with "and" or "or" are not possible yet. Put two conditions one after the other.
