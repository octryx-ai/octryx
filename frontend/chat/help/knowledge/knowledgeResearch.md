---
title: Research websites
---

The websites research may use or must avoid, for this Workspace or for all Workspaces.

### What you do here
- Open a website to approve, block or remove it; research proposes some by itself.
- Add a website yourself: a host such as docs.spring.io, optionally with a path.
- Choose the mode: **Open** or **Approved websites only**.

### Next steps
- [Search](/chat?area=knowledge&tab=knowledgeLibrary)
- [Open documents](/chat?area=knowledge&tab=knowledgeSources)

### The modes
- **Open**: chat web search may use any website except blocked ones. Research always reads only approved websites.
- **Approved websites only**: chat web search and research read only from approved websites. Anything else is skipped.
- A built-in platform blocklist always applies on top of the decisions here; the provider section names its version.

### Adding a website
- A host covers its subdomains, and a path covers everything below it. Wildcards are not needed.
- Shared hosts such as github.com need an owner path, for example github.com/spring-projects/spring-boot.
- Approval permits research from this website; it does not validate every claim on it.
- A block always wins over an approval.

### Search provider
- Without a search provider, web search and research cannot search. An instance administrator sets the provider key.
- Check provider sends one fixed test query; a failing check pauses the provider for a while, a passing check resumes it.
- Queries may contain Workspace data up to the classification the provider is cleared for.
