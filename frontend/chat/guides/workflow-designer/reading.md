---
title: Reading a workflow
order: 1
---

Start at **Start** and follow the arrows.

**The boxes**
- **Agent step**: an AI agent does work, for example "Minimal fix".
- **Check**: the platform checks the work, for example "Tests pass". It ends with *Passed* or *Failed*.
- **Condition**: the run goes one way or another, depending on a result or a ticket field.
- **Approval**, **Confirmation**, **Question to a person**: a person decides, confirms or answers.
- **Wait for an event**: the run waits, for example until the pull request is merged.
- **Platform action**: the platform does something itself, for example open a pull request.
- **End**: the run is over, for example *Done* or *Blocked*.

**The arrows**
- A label on an arrow says when it is taken, for example *Passed* or *Otherwise*.
- An arrow that leads back is a **way back**: the run tries again, at most as often as it says.

Click a box or an arrow to see its settings on the right.
