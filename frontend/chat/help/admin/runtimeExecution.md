---
title: Execution & storage
---

Where agent commands run, and where session files and artifacts are kept.

### What you do here
- Choose whether shell and script commands run on the host or in Docker.
- Set where session folders live and whether durable storage mirrors them.
- Set when old session folders are cleaned up.
- Choose the artifact store.
- Name the agent types whose answers must be backed by evidence.

### Next steps
- [Review command safety](/chat?area=admin&tab=commandSafety)

### The settings
- **Isolation**: where shell, CLI, kubectl and saved-script commands run, and what they may reach. **Container network**: *No network* cuts all network access, *Own network (bridge)* gives the container its own network, *The server's network (host)* shares the server's.
- **Workspace storage**: each chat session works in its own folder; durable storage mirrors it so files survive pod restarts.
- **Cleanup**: session folders older than the maximum age are deleted automatically; folders of running sessions are kept.
- **Artifact store**: where large tool artifacts and outputs are kept. S3 and GCS need credentials or pod identity.
- **Evidence grounding**: which answers must be backed by cited sources or live evidence. Turns of these agent types always obey the evidence-grounded answer contract. A selected workflow that requires sources or live evidence, and the Workspace policy, apply it too. The prompt's wording never decides. The list holds agent type keys, one per line; **Reset to the default list** returns to the platform's default.
