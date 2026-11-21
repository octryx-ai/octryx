# The demo (`docker-compose.demo.yml`)

A local demo, not for production: one command gives a Workspace anyone can click through, without Jira, GitHub or
any credential beyond the model access in `.env`.

```bash
docker compose -f docker-compose.yml -f docker-compose.demo.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.demo.yml logs demo   # ends with "demo: ready in the Workspace 'Demo Shop'"
```

## What it adds

| | |
|---|---|
| `demo-git` | a fake GitHub (`fake_github.py`): REST and git over bare repositories, in the API's network namespace on `127.0.0.1:8434` (`OCTRYX_DEMO_GIT_PORT`), published on the host's 127.0.0.1 only. The pull requests, comments, reviews and statuses it records: `curl http://127.0.0.1:8434/_fake/pulls`. Bot account: `demo-bot`. |
| `demo` | the one-shot seed (`seed_demo.py`, idempotent): the Workspace "Demo Shop", the repository `demo/demo-shop` on `demo-git`, the README and `docs/` of the Demo Shop as Knowledge, the connection "GitHub (demo)", the run repository with its test command, the PR review bot (trigger `sync`, status `inform`) and the work items OCX-1 (bug: the discount is subtracted as an amount) and OCX-2 (story: free shipping from 50.00). |
| `demo-shop/` | the sample app: plain Python 3, no dependencies; `python3 -m unittest discover -s tests`. |
| `sample-run/` | a sample run (`run.json`, when recorded): one real run of OCX-2 (Story / epic delivery) from another install, imported by the seed as a sample. The run views show it with a "Sample run" badge and its pull request #1 on `demo-git`; like any run of this install it shows in costs and dashboards. See `sample-run/README.md`. |

Everything the demo needs is in `docker-compose.demo.yml` and only there: `docker-compose.yml` alone starts no demo
service, publishes no demo port and relaxes nothing. With the demo file, the API reaches `demo-git` through the
loopback exemption `OCTRYX_SOURCE_SYNC_ALLOW_LOOPBACK_HOSTS=127.0.0.1:8434`, which it admits only in a
non-production runtime profile with loopback-only origins. The seed changes nothing without `OCTRYX_DEMO=1`, which only
the `demo` service sets; it acts as `admin` with a 15-minute token it signs itself, keeps it in memory and never
prints it. Without a usable Knowledge object store it skips the docs and says so.

To add the demo to a running install, run the same `up` command with both files; to remove it, `down` with both
files (add `-v` to drop its repository volume too) and start again with `docker-compose.yml` alone.

Clone the demo repository on the host: `git clone http://127.0.0.1:8434/demo/demo-shop.git`.

## Starting over

`docker compose -f docker-compose.yml -f docker-compose.demo.yml down -v` removes every volume, the demo's included (`demo_git_remotes`).
