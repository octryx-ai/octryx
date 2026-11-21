// Render guards for admin forms and side columns split into smaller functions: the skill editor fields, the skill
// detail side column and security tab, the repository quality form, the user account
// dialogs and the Google personal sign-in render the same structure after being split up.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import { load } from "./adminPartsLoader.mjs";
import { act, byTestId, server, text, tick } from "./settingsRenderHarness.mjs";
import { all, buttons, create, createAsync, includesAll, noop, plain, testIds } from "./adminGuardRenderers.mjs";

test("the skill editor fields show the frontmatter, the body, the Octryx fields and the availability", () => {
  const { SkillEditorFields } = load("admin/components/skillCatalog/SkillEditorFields.tsx");
  const { emptyForm } = load("admin/components/skillCatalog/skillEditorModel.ts");
  const changes = [];
  const categories = { categories: [{ id: "c1", key: "qa", label: "QA", archived: false, children: [{ id: "c2", key: "qa.lint", label: "Lint", archived: false, children: [] }] },
    { id: "c3", key: "old", label: "Old", archived: true, children: [] }] };
  const form = { ...emptyForm(), name: "Bad Name", description: "x".repeat(1030), outputContract: "ok: yes\nbroken line" };
  const view = create(createElement(SkillEditorFields, { form, isNew: true, licence: "MIT", categories, onChange: (patch) => changes.push(patch) }));
  const page = text(view.root);
  includesAll(page, ["Agent Skills fields (SKILL.md frontmatter)", "Name", "Licence (SPDX)", "Skills written here are Internal.",
    "1030 / 1024", "Instructions (SKILL.md body)", "Octryx fields", "Required tools · octryx-claude", "Optional tools · Platform chat",
    "Lines without key: value are dropped: broken line", "Availability", "Found with skill_search and loaded with skill_get."]);
  assert.equal(all(view, "section").length, 3);
  assert.equal(all(view, "textarea").length, 9);
  assert.deepEqual(all(view, "option").map((node) => text(node)), ["Choose a category…", "QA", "QA / Lint"]);
  assert.equal(byTestId(view, "skill-editor-note").length, 0);
  assert.equal(view.root.findAll((node) => node.props.className === "skills__er" && node.type === "small").length, 1);
  byTestId(view, "skill-editor-tools-platform_chat-optional")[0].props.onChange({ target: { value: "web" } });
  assert.deepEqual(plain(changes[0].tools.platform_chat), { required: "", optional: "web" });
  byTestId(view, "skill-editor-available-octryx_claude")[0].props.onClick();
  assert.deepEqual(plain(changes[1]), { availableOctryxClaude: !form.availableOctryxClaude });

  const edit = create(createElement(SkillEditorFields, { form: emptyForm(), isNew: false, licence: "MIT", categories, onChange: noop }));
  includesAll(text(edit.root), ["The name of a skill cannot change.", "Detected from the source; not editable here.", "Change note (optional)"]);
  assert.equal(byTestId(edit, "skill-editor-note").length, 1);
});

const version = (patch = {}) => ({
  id: "v2", version: 2, state: "draft", digest: "sha256:abc", bundle_digest: "sha256:bundle0123456789", licence_spdx: "MIT",
  available_platform_chat: true, available_octryx_claude: false, scripts_allowed: false, scripts_reason: null,
  acknowledged_findings: [], extension: { allowed_roles: ["dev"] }, upstream: { commit: "abcdef1234567" },
  files: [{ path: "SKILL.md", sha256: "x", size: 1, kind: "skill" }, { path: "run.sh", sha256: "y", size: 1, kind: "script" }],
  security_report: { spec: [{ code: "s1", severity: "warning", field: "description", message: "Too short" }], findings: [
    { id: "f1", rule: "secret", severity: "high", message: "Looks like a key", file: "run.sh", line: 3, effect: "withheld", acknowledge: true, blocks: true },
    { id: "f2", rule: "net", severity: "info", message: "Calls out", file: null, line: null, effect: "none", acknowledge: false, blocks: false },
  ], summary: { high: 1, medium: 0, info: 1 } }, ...patch,
});
const detail = (patch = {}) => ({
  id: "sk_1", name: "helper", kind: "skill", tags: ["qa", "lint"], owner_id: "owner-123456789", versions: [], tracking_mode: "follow",
  pinned_commit: "1234567abcdef", upstream_path: "skills/helper", category: { id: "c1", key: "qa", label: "QA", path: ["QA", "Lint"] },
  source: { id: "s1", label: "acme/skills", trust: "official", kind: "git", url: "https://git.example/acme", ref: "main" },
  upstream_status: { latest_commit: "fedcba9876543", update_available: true, checked_at: "2026-01-02T03:04:05Z", path_moved: { from: "a", to: "b" } },
  open: { ...version(), state: "draft" }, published: { ...version({ version: 1, state: "published" }) }, new_findings: [], ...patch,
});

test("the skill detail side column shows catalog, availability, provenance and the security summary", async () => {
  const srv = server(() => ({ status: 200, body: {} }));
  const { SkillDetailSide } = load("admin/components/skillCatalog/SkillDetailSide.tsx", { fetch: srv.fetch });
  const opened = [];
  const view = create(createElement(SkillDetailSide, { detail: detail(), version: version(), onOpenCategory: (key) => opened.push(key), onOpenSecurity: noop, onChanged: async () => {} }));
  const page = text(view.root);
  includesAll(page, ["Catalog", "Skill (Agent Skills format)", "QA / Lint", "#qa", "#lint", "dev", "Available in", "Platform chat",
    "Delivered as /octryx:helper", "Provenance", "acme/skills", "Official", "https://git.example/acme @ main", "skills/helper",
    "folder moved to b", "new", "checked 2026-01-02 03:04", "Follow upstream (main)", "Security review", "1 high", "0 medium", "1 info"]);
  assert.equal(all(view, "section").length, 4);
  assert.equal(all(view, "dt").length, 13);
  assert.equal(view.root.findAll((node) => node.props.role === "switch").length, 2);
  byTestId(view, "skill-detail-category")[0].props.onClick();
  assert.deepEqual(opened, ["qa"]);
  act(() => byTestId(view, "skill-detail-tags-edit")[0].props.onClick());
  assert.equal(byTestId(view, "skill-detail-tags-input")[0].props.value, "qa, lint");
  assert.deepEqual(buttons(view).filter((label) => label === "Save" || label === "Cancel"), ["Save", "Cancel"]);

  const mcp = create(createElement(SkillDetailSide, { detail: detail({ kind: "mcp_server", source: null, upstream_path: null, tags: [], category: null }),
    version: null, onOpenCategory: noop, onOpenSecurity: noop, onChanged: async () => {} }));
  includesAll(text(mcp.root), ["MCP server entry (from a plugin)", "none", "every role", "Written here", "Not available: a local process"]);
  assert.equal(all(mcp, "dt").length, 8);
  await tick();
});

test("the skill security tab groups findings, offers acknowledgements and the scripts switch on a draft", () => {
  const { SkillSecurityTab } = load("admin/components/skillCatalog/SkillSecurityTab.tsx");
  const view = create(createElement(SkillSecurityTab, { detail: detail({ new_findings: [{ rule: "secret", file: "run.sh" }] }), version: version(), onChanged: async () => {} }));
  includesAll(text(view.root), ["1 new finding against the published v1: secret (run.sh).", "Automated review of v2", "Spec · description",
    "Too short", "High · 1", "Info · 1", "run.sh:3 · on delivery: withheld · blocks publishing", "Acknowledged for this version",
    "Scripts for this version", "Off: run.sh is not delivered."]);
  assert.equal(byTestId(view, "skill-finding-ack-f1").length, 1);
  assert.equal(byTestId(view, "skill-findings-save")[0].props.disabled, true);
  act(() => byTestId(view, "skill-finding-ack-f1")[0].props.onChange({ target: { checked: true } }));
  assert.equal(byTestId(view, "skill-findings-save")[0].props.disabled, false);
  act(() => byTestId(view, "skill-scripts-switch")[0].props.onClick());
  assert.equal(byTestId(view, "skill-scripts-reason").length, 1);
  assert.equal(byTestId(view, "skill-scripts-save")[0].props.disabled, true);

  const published = create(createElement(SkillSecurityTab, { detail: detail({ open: null }), version: version({ scripts_allowed: true, scripts_reason: "needed",
    security_report: { spec: [], findings: [], summary: { high: 0, medium: 0, info: 0 } } }), onChanged: async () => {} }));
  includesAll(text(published.root), ["No findings and no spec issues.", "Allowed for this version: needed."]);
  assert.equal(byTestId(published, "skill-new-findings").length, 0);
});

test("the repository quality form edits the default policy and keeps the expert JSON", () => {
  const { ProjectRepoQualityForm } = load("admin/components/projectsTab/policies/ProjectRepoQualityForm.tsx");
  const drafts = [];
  const props = { projectQualityDraft: '{"default": {"linter": "ruff", "sast_runners": ["semgrep"]}}', setProjectQualityDraft: (value) => drafts.push(value),
    projectQualityError: null, projectQualityLoading: false, onSubmit: noop };
  const view = create(createElement(ProjectRepoQualityForm, props));
  includesAll(text(view.root), ["Repository quality policy", "Default test command", "SAST runners", "Require green baseline before changes",
    "Expert repository quality JSON", "Save Repository Quality"]);
  const inputs = all(view, "input");
  assert.deepEqual(inputs.map((node) => node.props.value ?? node.props.checked), ["", "ruff", "semgrep", false]);
  inputs[1].props.onChange({ target: { value: " " } });
  inputs[0].props.onChange({ target: { value: "pytest " } });
  assert.deepEqual(JSON.parse(drafts[0]), { default: { sast_runners: ["semgrep"] } });
  assert.deepEqual(JSON.parse(drafts[1]), { default: { linter: "ruff", sast_runners: ["semgrep"], test_runner: "pytest" } });
  const cleared = create(createElement(ProjectRepoQualityForm, { ...props, projectQualityDraft: '{"default": {"linter": "x"}}' }));
  all(cleared, "input")[1].props.onChange({ target: { value: "" } });
  assert.deepEqual(JSON.parse(drafts[2]), {});
  const broken = create(createElement(ProjectRepoQualityForm, { ...props, projectQualityDraft: "[1", projectQualityError: "Bad JSON", projectQualityLoading: true }));
  includesAll(text(broken.root), ["Fix the expert JSON before using structured controls.", "Bad JSON", "Saving…"]);
  assert.ok(all(broken, "input").every((node) => node.props.disabled));
  all(broken, "input")[0].props.onChange({ target: { value: "x" } });
  assert.equal(drafts.length, 3);
});
