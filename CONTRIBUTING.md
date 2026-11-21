# Contributing to Octryx AI

Thank you for helping. Octryx AI is an alpha: things change fast, so a short note before a big change saves work on
both sides.

## Issues

- **Bugs:** open an issue with the bug report template: what you did, what you expected, what happened, and your
  version or commit.
- **Ideas:** open an issue with the feature request template and describe the problem before the solution.
- **Security problems:** never in an issue; see [Reporting a vulnerability](README.md#reporting-a-vulnerability).

## Pull requests

Pull requests are welcome. `main` holds the released version; work for the next release happens on the version
branch (for example `0.0.2`). Fork the repository and open your pull request against that version branch, not
against `main`. The maintainer merges the version branch into `main` when the release is cut. Please:

1. Open an issue first for anything bigger than a small fix, so we can agree on the approach.
2. Keep a pull request to one change, with tests for what it changes.
3. Run the checks for the parts you changed before you push; a pull request is merged only when they pass.

   **Backend** (Python 3.12 and [uv](https://docs.astral.sh/uv/)), from the repository root:

   ```bash
   (cd backend && uv sync --frozen --extra dev)
   backend/.venv/bin/ruff check backend
   backend/.venv/bin/pytest backend/tests
   ```

   Pass test files instead of `backend/tests` to run only the tests for your change.

   **Web app** (Node.js 22):

   ```bash
   cd frontend/chat
   npm ci
   npx tsc --noEmit
   npm run lint
   npm test
   ```

   **Launcher** (`clients/octryx-claude`):

   ```bash
   cd clients/octryx-claude
   uv venv --python 3.12
   uv pip install -r pyproject.toml pytest pytest-asyncio pytest-xdist
   .venv/bin/pytest
   ```
4. Describe in the pull request what changed and how you tested it (the template asks for it).
5. Sign off every commit (`git commit -s`). The `Signed-off-by:` line certifies the
   [Developer Certificate of Origin](https://developercertificate.org/): you wrote the change or have the right to
   submit it under the project's licence.

The documentation (<https://octryx.ai/docs/>) explains how the platform is built.

## Where things are and how code is written

- `backend/` is the FastAPI platform (routes in `app/api`, logic in `app/services`, the agent runtime in `app/agent`,
  tests in `tests/`), `frontend/chat/` the web app, `clients/octryx-claude/` the launcher on a developer's machine,
  `deployment/` the Helm chart and local setups.
- Code, comments, identifiers and documentation are in English.
- Small modules and short functions; comments say why, not what.
- No secrets, tokens or personal data in code, tests or logs.

## Licence

Octryx AI is licensed under the [Apache License 2.0](LICENSE). Contributions are accepted under the same licence
(inbound = outbound, as in section 5 of the licence). There is no contributor licence agreement (CLA) to sign; the
sign-off on each commit (see above) is all that is needed.

## Code of Conduct

Everyone taking part follows the [Code of Conduct](README.md#code-of-conduct).
