"""Platform actions of workflow runs: deterministic server-side steps on named connections.

Every action dispatches the same governed tools an agent would call (registry dispatch: tool approval gate,
capability class, named-connection routing, audit) under the action's fixed class, so no Jira, SCM or CI
credential ever leaves the server and no model is in the loop.
"""
