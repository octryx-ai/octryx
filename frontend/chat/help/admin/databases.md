---
title: Databases
---

Databases agents may query, only through query tools you define.

### What you do here
- Add a database: its type, address and a read-only account.
- Open a database to check its health, add query tools, pause or remove it.
- Read the recent queries by agents (the second table).

### Next steps
- [Open connections](/chat?area=admin&tab=adminConnections)
- [Open MCP servers](/chat?area=admin&tab=mcp)

### How queries stay safe
Agents answer questions from your databases only through **query tools** you define. Every query:

- runs read-only (SELECT or WITH), always;
- takes parameters instead of pasted SQL, never free SQL;
- returns at most the tool's row limit and stops at its timeout;
- is audited.

Removing a database takes its query tools away from every agent and deletes the stored password; the removal is audited.

### The database table
- **Query tools**: how many query tools agents can use on the database. Without one, agents cannot use it.
- **State**: *Working* after a successful check, *Failing* when the last check failed (hover for the cause),
  *Needs a query tool* while it has none, *Not checked yet*, or *Paused*. A paused database keeps its settings, but
  agents cannot query it until you resume it.
- **Needs attention** shows only the active databases that fail their check or have no query tool.

### Recent queries
The latest queries agents ran through query tools: when, which tool on which database, who ran it in which Workspace,
and the result: the number of rows (marked when the row limit cut the answer) or why it failed.
