# Agent models

Agent definitions and their revisions, skills and the skill catalog, device jobs on a person's own devices,
local Claude Code sessions and stored session transcripts.

## Invariants

- A revision number is unique per agent definition (`uq_agent_definition_revision_number`,
  `agent_definition_revision.py`).
- A device job event is stored once per job and sequence number (`uq_device_job_events_seq`, `device_job.py`).
- A transcript batch is stored once per Workspace, session, stream and first line
  (`session_transcript.py`), so a batch sent again is not stored twice.
- A published skill version changes only by its move to `retired` (`runtime/governed_revision`, installed in
  `skill_catalog.py`).
