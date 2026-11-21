# Octryx plugins: build your own

A plugin adds to Octryx what your team needs: skills, workflows, roles, a connection to your own MCP server and
pages in the Octryx UI. Anyone can build one; it is a folder with a manifest, developed in its own repository.
`release-notes/` in this folder is a complete example.

Installing a plugin is putting it into the Octryx image's plugin folder. An admin then switches it on in a Workspace;
that is the only limit. Whoever builds the image and switches a plugin on is responsible for it. Every change is in the
audit log.

## The folder

```
octryx-plugin.yaml          id, version, what it brings, what it uses and writes
skills/<name>/SKILL.md      Agent Skills format; folder name = skill name; more files next to it
workflows/<key>.yaml        {key, name, description, definition}: the workflow designer's format
roles/<key>.yaml            {key, name, description, function_keys, functions: [{key, name, tools}]}
settings.schema.json        optional: JSON schema of the plugin's settings (format: password → secret store)
ui/dist/                    optional: static pages (index.html, js, css) shown inside Octryx
```

`octryx-plugin.yaml`:

```yaml
apiVersion: octryx.ai/plugin/v1
id: acme.release-gate            # publisher.name, lower case; never changes
name: Release gate
version: 1.0.0                   # semver; a new version upgrades the installed one in place
publisher: ACME
description: Go / no-go before a release.
license: Apache-2.0
contributes:
  skills: [skills/release-gate]
  workflows: [workflows/release-gate.yaml]
  roles: [roles/release-gate.yaml]
  mcp_servers: [{name: acme-gate, url: "https://gate.acme.example/mcp", tools: [check_release]}]
  ui:
    bundle: ui/dist
    pages: [{id: gate, title: Release gate, area: work}]     # area: work | knowledge | operations | admin
    phone: [{id: gate, title: Release gate}]
    methods: [list_jira_versions, acme-gate.check_release, settings.get]   # Octryx tools, <server>.<tool>
permissions:
  connections: [jira]            # the Workspace connections it uses
  egress: [gate.acme.example]    # every host it connects to
  writes: []                     # every connection kind it writes to (jira, confluence, github, ...)
settings: settings.schema.json
```

Rules the check enforces:

- a workflow step that writes (`jira.*`, `confluence.*`, `scm.*`) is declared in `permissions.writes`;
- an MCP server is `https`, and its host is listed in `permissions.egress`;
- skills pass the skill catalog's checks (a secret in a skill refuses the install);
- names that already exist in Octryx (skill, workflow key, role, function, MCP server) refuse the install.

## UI pages

The files under `ui/dist` are shown in a sandboxed frame: no network access, no cookies. The page talks to Octryx only
through `bridge.js` (copy it from `release-notes/ui/dist/`):

```js
const ctx = await octryx.context();   // {workspace_id, user, theme: {mode, tokens}, locale, slot: {kind: "page" | "phone", id}}
const versions = await octryx.call("list_jira_versions", {project: "SHOP"});
octryx.resize();                              // tell the frame the page's height
```

Only the `methods` the manifest declares can be called, always with the rights of the person looking at the page.
A write that needs a confirmation answers `confirmation_required`, and Octryx asks that person.

## Check it

```sh
python backend/scripts/octryx_plugin.py validate path/to/my-plugin     # the same checks as the install; for CI
python backend/scripts/octryx_plugin.py pack path/to/my-plugin          # → acme.release-gate-1.0.0.zip
```

## Install it

**Put it into your Octryx image.** Octryx reads every plugin in `/opt/octryx/plugins` at every start:

```dockerfile
FROM <your octryx image>
COPY my-plugin/ /opt/octryx/plugins/my-plugin/
# or a packed one:  COPY acme.release-gate-1.0.0.zip /opt/octryx/plugins/
# the examples of this repository are in the image too:
RUN cp -r /opt/octryx/plugin-examples/release-notes /opt/octryx/plugins/
```

Without your own image (Helm), mount a volume at the same folder:

```yaml
plugins:
  volume: {configMap: {name: octryx-plugins}}     # zip files as binaryData, or a PVC, or any volume source
```

**Switch it on in a Workspace.** Workspace › Plugins lists the plugins of the image with a few plain lines on what each
brings and may do. A Workspace admin (or a platform admin) switches a plugin on or off there:

- on: its workflows, roles and pages appear in that Workspace, its skills reach it, its MCP servers are allowed there;
- off: all of it is gone from that Workspace, nothing is deleted; on again brings it back with its settings;
- other Workspaces see nothing of it until their admin switches it on.

## A new image

- A new version in the image upgrades the plugin at the next start, in every Workspace where it is on. An image
  rollback rolls it back.
- Take a plugin out of the folder and it is switched off everywhere at the next start, not deleted. Put it back and
  it is on again where it was on. A Workspace whose admin switched it off stays off.
- A plugin that fails the check or conflicts is skipped, and Octryx starts anyway. The reason is in the log and, for
  platform admins, in `GET /api/v1/plugins/image`.
- Start changes are recorded as made by the account `octryx-image-plugins`. That account is inactive: nobody can sign
  in with it.

Whatever the old and the new version both bring is updated in place and keeps its id: a skill or workflow gets a new
published version (the previous one stays in the history), roles get their new tools. Content that did not change
gets no new version. Anything only the new version brings is added. Anything only the old version brought is
switched off and kept. Settings stay as they were. An upgrade waits (reason in the report) while an admin has an open
draft of one of the plugin's skills: publish or discard it, and the next start upgrades.

## External MCP servers

Octryx does not start a container for a plugin: `contributes.server` is validated and recorded on the install. Run
your MCP server next to Octryx (Compose, Helm) and connect it by URL with `contributes.mcp_servers`.
