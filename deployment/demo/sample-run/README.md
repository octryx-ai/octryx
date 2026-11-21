# The sample run

`run.json` here is a sample run bundle (`backend/scripts/run_bundle.py`): one finished run of OCX-2 ("Free shipping
from 50.00", workflow `epic-delivery`) with the PR review bot's run on its pull request, their sessions, tool calls,
turn traces, usage and the device job of its seat. The person appears as `demo`, the device as the revoked placeholder
"Sample device", and the GitHub and app addresses as placeholders the import fills in.

The demo seed imports it into the Workspace "Demo Shop" as a sample: the run views show it with a "Sample run" badge,
and its pull request (commits, comments, reviews and statuses) is replayed on the demo's fake GitHub (`demo-git`,
`fake_github.py`) for the repository `demo/demo-shop`. The demo is its own install with its own database, so the run
also shows in costs and dashboards there, like any run. The import runs only in the demo (`OCTRYX_DEMO=1` and a
non-production runtime profile).

Record a new one on the stack that ran the run, then check it here before committing it:

```bash
python backend/scripts/run_bundle.py export --run <run id> --github <that stack's fake GitHub> --app-base <its URL> --out run.json
python backend/scripts/run_bundle.py check deployment/demo/sample-run/run.json   # size, secrets, forbidden names
```

Without `run.json` the demo has no sample run; everything else works the same.
