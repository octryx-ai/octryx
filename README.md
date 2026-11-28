# Octryx AI

**The layer above your coding agents.** Your developers keep Claude Code or Codex.
Octryx AI gives the whole team one process, one set of rules and one record, from an idea in chat to a reviewed pull
request. Open source, self-hosted.

- Website: <https://octryx.ai>
- Documentation: <https://octryx.ai/docs/>
- Benchmark: <https://github.com/octryx-ai/octryx-bench>

## Status: v0.0.2-alpha

Early and changing: expect rough edges and breaking changes. Do not run this alpha with production data or expose it
to the internet. See the [known limitations](#known-limitations).

> **No warranty — use at your own risk.** Octryx is provided "AS IS", without warranties or conditions of any kind. You use it at your own risk and are responsible for its use, including what its agents do in connected systems. To the extent permitted by applicable law, the authors and contributors are not liable for any damages arising from its use (Apache License 2.0, sections 7 and 8). This alpha is not intended for production data or production systems.

## Try it: the local demo

A Workspace to click through on your own machine: a sample app on a local fake GitHub, its docs as Knowledge, a PR
review bot and two work items. You need Docker with `docker compose` 2.23+ (at least 4 GB memory and 25 GB free disk)
and access to one model (Anthropic, an OpenAI-compatible endpoint or AWS Bedrock). The first start takes about 5
minutes plus the image download.

Before the first `up`, set one model block in `.env`: `LLM_PROVIDER`, `AGENT_DEFAULT_MODEL` and its key or AWS
credentials. Without them compose refuses to start.

```bash
git clone https://github.com/octryx-ai/octryx.git && cd octryx
cp .env.example .env        # set LLM_PROVIDER, AGENT_DEFAULT_MODEL and the key of ONE model block
docker compose -f docker-compose.yml -f docker-compose.demo.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.demo.yml logs api | grep "setup code"
```

Open <http://localhost:8000/chat/setup>, enter the setup code and create your administrator, then open the Workspace
**Demo Shop**. Everything listens on `127.0.0.1` only.

The full walkthrough (the three ways to try the demo, pairing Claude Code, ports, stopping and starting over):
[local demo](https://octryx.ai/docs/start/first-run). Installs without the demo: [Docker](https://octryx.ai/docs/install/docker),
[Kubernetes](https://octryx.ai/docs/install/kubernetes), [upgrade and backup](https://octryx.ai/docs/install/upgrade),
[troubleshooting](https://octryx.ai/docs/start/troubleshooting).

## Learn more

- [Run a coding agent through Octryx AI](https://octryx.ai/docs/install/launcher)
- [Sensitive content handling](https://octryx.ai/docs/security/sensitive-content)
- [Architecture](https://octryx.ai/docs/concepts/architecture) and [repository layout](https://octryx.ai/docs/contribute/dev-setup#the-parts-of-the-repository)
- [HTTP API](https://octryx.ai/docs/admin/api)

## Known limitations

The alpha's known limitations are listed in the documentation:
[known limitations](https://octryx.ai/docs/start/known-limitations).

**Security note:** 0.0.2 fixes [GHSA-h4xh-8wqf-rxj4](https://github.com/octryx-ai/octryx/security/advisories/GHSA-h4xh-8wqf-rxj4):
in v0.0.1-alpha the Codex device mode applied a repository's own Codex configuration. Upgrade from v0.0.1-alpha.

## Contributing

Issues and pull requests are welcome; please read [CONTRIBUTING.md](CONTRIBUTING.md) first. Everyone taking part
follows the [Contributor Covenant 2.1](https://www.contributor-covenant.org/version/2/1/code_of_conduct/).

## Reporting a vulnerability

Report security problems **privately** on GitHub: **Security › Report a vulnerability**. Never open a public issue for
a security problem. Details: [security policy](https://octryx.ai/docs/contribute/report#security-issues).

## Licence

[Apache License 2.0](LICENSE).
