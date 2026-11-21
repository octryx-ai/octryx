import assert from "node:assert/strict";
import { test } from "node:test";
import {
  blockingIssues, buildExtension, buildFrontmatter, createBody, editorChecks, emptyForm, formFromVersion, parseContract, saveBody,
  skillMdText,
} from "../../src/admin/components/skillCatalog/skillEditorModel.ts";
import {
  canFollow, defaultSelection, gitImportBody, importLabel, importedIds, itemOffer,
} from "../../src/admin/components/skillCatalog/skillImportModel.ts";

const version = {
  version: 3, state: "draft", digest: "sha256:abc", category_id: "cat-1", available_platform_chat: true, available_octryx_claude: false,
  note: null, body: "# Body\n",
  frontmatter: { name: "release-notes", description: "Write notes.", metadata: { owner: "team" }, "allowed-tools": "Bash" },
  extension: {
    tools: { platform_chat: { required: ["skill_get"], optional: [] }, octryx_claude: { required: ["Bash(git log *)"], optional: ["Read"] } },
    output_contract: { format: "markdown" }, safety_rules: ["Never push."], allowed_roles: ["admin"], executor_type: "llm_interpret",
  },
};

test("a save keeps upstream frontmatter and extension keys and overwrites only the edited fields", () => {
  const { form, base } = formFromVersion(version, ["docs"]);
  assert.equal(form.tools.octryx_claude.required, "Bash(git log *)");
  assert.equal(form.outputContract, "format: markdown");
  const edited = { ...form, name: "renamed", description: "Write release notes.", whenToUse: "", safetyRules: "Never push.\nAsk first." };
  const body = saveBody(edited, base);
  assert.deepEqual(body.frontmatter, { name: "release-notes", description: "Write release notes.", metadata: { owner: "team" }, "allowed-tools": "Bash" });
  assert.equal(body.extension.executor_type, "llm_interpret");
  assert.deepEqual(body.extension.safety_rules, ["Never push.", "Ask first."]);
  assert.deepEqual(body.extension.output_contract, { format: "markdown" });
  assert.equal(body.available_octryx_claude, false);
  assert.equal("when_to_use" in buildFrontmatter({ ...form, whenToUse: "On release days" }, base), true);
});

test("a new skill body carries the name, the frontmatter, the tools per surface and the tags", () => {
  const form = { ...emptyForm(), name: "release-notes", description: "Write notes.", categoryId: "cat-1", tags: "Docs, docs, release",
    roles: "Admin, operator" };
  const body = createBody(form);
  assert.equal(body.name, "release-notes");
  assert.deepEqual(body.frontmatter, { name: "release-notes", description: "Write notes." });
  assert.deepEqual(body.tags, ["docs", "release"]);
  assert.deepEqual(buildExtension(form, null).allowed_roles, ["admin", "operator"]);
  assert.deepEqual(body.extension.tools.platform_chat, { required: [], optional: [] });
  assert.deepEqual(parseContract("format: markdown\nbroken line\nsections: Summary, Risks"), { format: "markdown", sections: "Summary, Risks" });
});

test("live checks mirror the spec rules and name the stripped permission keys", () => {
  const { form, base } = formFromVersion(version, []);
  const checks = Object.fromEntries(editorChecks(form, base).map((check) => [check.id, check.tone]));
  assert.equal(checks.name, "ok");
  assert.equal(checks.stripped, "wa");
  assert.equal(checks.category, "ok");
  const bad = { ...emptyForm(), name: "Bad_Name", body: "!`rm -rf`" + "\n".repeat(600) };
  const tones = Object.fromEntries(editorChecks(bad, null).map((check) => [check.id, check.tone]));
  assert.deepEqual([tones.name, tones.description, tones.lines, tones.category, tones.shell], ["er", "er", "wa", "er", "er"]);
  assert.equal(blockingIssues(bad, true).length, 3);
  assert.equal(blockingIssues({ ...bad, name: "" }, false).length, 2);
  assert.match(skillMdText({ name: "a", description: "b", metadata: { k: 1 } }, "# A"), /^---\nname: a\ndescription: b\nmetadata: \{"k":1\}\n---\n\n# A$/);
});

const inspect = {
  url: "https://example.invalid/repo", ref: "main", commit: "a".repeat(40), path: "", plugin: null, licence: null, ignored: [],
  skills: [
    { kind: "skill", path: "skills/one", name: "one", files: 2, importable: true, licence: { spdx: "MIT", source: "repository", allowed: true }, existing: null },
    { kind: "skill", path: "skills/two", name: "two", files: 1, importable: true, licence: { spdx: "MIT", source: "repository", allowed: true },
      existing: { skill_id: "s-2", relation: "update", kind: "skill" } },
    { kind: "skill", path: "skills/bad", name: "bad", files: 1, importable: false, spec_issues: [{ code: "x", severity: "error", message: "Bad." }],
      licence: { spdx: null, source: "none", allowed: false }, existing: null },
  ],
  mcp_servers: [{ kind: "mcp_server", path: "plugin", name: "srv", files: [".mcp.json"], importable: true,
    licence: { spdx: "MIT", source: "repository", allowed: true }, existing: null }],
};

test("an inspection offers only new importable items and imports exactly the inspected commit", () => {
  assert.deepEqual(defaultSelection(inspect), ["skill:skills/one:one", "mcp_server:plugin:srv"]);
  assert.match(itemOffer(inspect.skills[1]).reason, /use its update/);
  assert.equal(itemOffer(inspect.skills[2]).importable, false);
  const request = { url: " https://example.invalid/repo ", ref: "main", path: "", marketplacePlugin: "" };
  const body = gitImportBody(request, inspect, [...defaultSelection(inspect), "skill:skills/two:two"],
    { categoryId: "cat-1", tracking: "follow", trust: "community", tags: ["x"] });
  assert.equal(body.commit, "a".repeat(40));
  assert.equal(body.url, "https://example.invalid/repo");
  assert.deepEqual(body.items.map((item) => [item.name, item.tracking_mode]), [["one", "follow"], ["srv", "follow"]]);
  const pinned = gitImportBody(request, { ...inspect, ref: "HEAD" }, ["skill:skills/one:one"], { categoryId: "c", tracking: "follow", trust: "", tags: [] });
  assert.equal(pinned.items[0].tracking_mode, "pinned");
  assert.equal("trust" in pinned, false);
  const market = { ...inspect, plugin: { name: "p", marketplace_commit: "b".repeat(40) } };
  assert.equal(gitImportBody({ ...request, marketplacePlugin: "p" }, market, [], { categoryId: "c", tracking: "pinned", trust: "", tags: [] }).commit, "b".repeat(40));
  assert.deepEqual([canFollow("main"), canFollow(""), canFollow("HEAD"), canFollow("c".repeat(40))], [true, false, false, false]);
  assert.equal(importLabel([{ kind: "skill" }, { kind: "skill" }, { kind: "mcp_server" }]), "Import 2 skills and 1 MCP server entry as drafts");
  assert.deepEqual(importedIds({ imported: [{ skill_id: "a" }, { skill_id: "b" }] }), ["a", "b"]);
  assert.deepEqual(importedIds({ skill_id: "c", name: "x" }), ["c"]);
});
