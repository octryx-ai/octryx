---
title: Approvals and questions
order: 4
---

Three boxes let a person take part.

**Approval**
- A person approves or rejects, for example "Merge the bug fix".
- **Who decides**: for example the person who started the run, the ticket's assignee, or anyone with a role.
- The platform makes sure the person who approves is not the person who asked (four eyes).
- Ways out: *Approved* and *Rejected*.

**Confirmation**
- A person confirms something the agent prepared, for example the reproduction or the test plan.
- Ways out: *Confirmed*, *Asked for changes*, *Stopped*. *Asked for changes* usually leads back to the agent step.

**Question to a person**
- The run asks a question and waits for the answer, for example "Which branch should the pull request target?".
- It has one way out; the answer goes to the next step.

The person sees the approval, confirmation or question in the app, with the run it belongs to.
