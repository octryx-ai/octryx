"""Session episodes: what a session learned, returned to the Workspace Knowledge as a governed source.

An episode summary of a platform chat session or of an external CLI session (Claude Code, Codex,
OpenCode over the Knowledge MCP) is written as an ordinary source revision through the normal
ingestion, so the projection outbox makes it searchable and graph-extractable like any other source.
Its citation links to the session it came from.
"""
