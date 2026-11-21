// Render guards for admin catalog and drawer components split into smaller functions: the skill review drawer and
// editor, the skill sources tab, a prompt's detail drawer, the runs page and run drawer, a plugin frame, the hand-written
// Cedar editor and the knowledge packages panel render the same structure after being split up.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { load } from "./adminPartsLoader.mjs";
import { act, byTestId, server, text, tick } from "./settingsRenderHarness.mjs";

async function createAsync(element) {
  let view;
  await act(async () => { view = TestRenderer.create(element); });
  await tick();
  return view;
}

const all = (view, type) => view.root.findAll((node) => node.type === type);
const buttons = (view) => all(view, "button").map((node) => text(node));
const includesAll = (page, parts) => { for (const part of parts) assert.ok(page.includes(part), part); };

const security = { spec: [], findings: [], summary: { high: 0, medium: 0, info: 0 } };
const skillVersion = (state, patch = {}) => ({
  id: `v-${state}`, version: state === "published" ? 1 : 2, state, digest: `sha256:${state}0123456789`, bundle_digest: "b",
  category_id: null, available_platform_chat: true, available_octryx_claude: false, licence_spdx: "MIT", scripts_allowed: false,
  scripts_reason: null, scripts_allowed_by: null, acknowledged_findings: [], upstream: null, base_version: null, note: null,
  created_by: "u1", created_at: null, updated_at: null, submitted_by: null, submitted_at: null, approval_id: null,
  published_by: null, published_at: null, retired_at: null, files: [{ path: "SKILL.md", sha256: "x", size: 10, kind: "skill" }],
  security_report: security, merge_report: null, launch_spec: null, frontmatter: { name: "helper", description: "Helps" },
  body: "Do it.", extension: {}, ...patch,
});
const skillDetail = (patch = {}) => ({
  id: "sk_1", name: "Review helper", kind: "skill", tags: ["qa"], owner_id: "u1", tracking_mode: null, pinned_commit: null,
  upstream_path: null, upstream_status: null, source: null, category: null, published: skillVersion("published"),
  open: skillVersion("draft", { note: "Better wording" }), review: null, new_findings: [], versions: [], ...patch,
});

test("the skill review drawer shows the timeline, the summary, the diff and the submit action", async () => {
  const srv = server((call) => {
    if (call.url.includes("/approval-rule")) return { status: 200, body: { rule: "four_eyes" } };
    if (call.url.includes("/diff")) return { status: 200, body: { files: [{ path: "SKILL.md", status: "modified", added: 2, removed: 1, lines: [], truncated: false }] } };
    if (/\/skills\/sk_1$/.test(call.url)) return { status: 200, body: skillDetail() };
    return { status: 200, body: {} };
  });
  const { SkillReviewDrawer } = load("admin/components/skillCatalog/SkillReviewDrawer.tsx", { fetch: srv.fetch });
  const view = await createAsync(createElement(SkillReviewDrawer, { skillId: "sk_1", onClose() {}, onChanged() {} }));
  await tick();
  const page = text(view.root);
  includesAll(page, ["Review and publish", "Review helper · v2", "Draft", "submit to freeze", "In review", "a second platform admin approves",
    "Published", "needs a second admin", "Summary", "Change", "Digest", "frozen on submit", "Surfaces", "Files changed",
    "SKILL.md +2/−1", "Changes against published v1", "SKILL.md (+2 / −1)"]);
  assert.equal(byTestId(view, "skill-review-drawer").length, 1);
  assert.equal(byTestId(view, "skill-review-summary").length, 1);
  assert.equal(byTestId(view, "skill-review-submit").length, 1);
  assert.equal(text(byTestId(view, "skill-review-submit")[0]), "Submit for review");
  assert.equal(all(view, "dt").length, 5);
  act(() => view.unmount());

  const none = server((call) => (/\/skills\/sk_2$/.test(call.url)
    ? { status: 200, body: skillDetail({ id: "sk_2", open: null, published: null }) } : { status: 200, body: {} }));
  const { SkillReviewDrawer: Empty } = load("admin/components/skillCatalog/SkillReviewDrawer.tsx", { fetch: none.fetch });
  const empty = await createAsync(createElement(Empty, { skillId: "sk_2", onClose() {}, onChanged() {} }));
  assert.ok(text(empty.root).includes("This skill has no open or published version."));
  assert.deepEqual(buttons(empty).filter((label) => label === "Close").length >= 1, true);
  act(() => empty.unmount());
});

test("the skill editor shows the head, the actions and the form; a new skill starts as draft v1", async () => {
  const srv = server((call) => {
    if (call.url.endsWith("/skills/sk_1")) return { status: 200, body: skillDetail() };
    if (call.url.endsWith("/skills/sk_1/edit")) return { status: 200, body: { ...skillVersion("draft"), created: true, base_version: 1 } };
    return { status: 200, body: {} };
  });
  const { SkillEditorPage } = load("admin/components/skillCatalog/SkillEditorPage.tsx", { fetch: srv.fetch });
  const props = { categories: { categories: [] }, onCancel() {}, onSaved() {}, onOpenReview() {} };
  const fresh = await createAsync(createElement(SkillEditorPage, { ...props, skillId: null }));
  includesAll(text(fresh.root), ["← Skills", "New skill", "A new skill starts as draft v1.", "Cancel", "Save draft", "Save and submit for review"]);
  assert.equal(byTestId(fresh, "skill-editor-form").length, 1);
  assert.equal(byTestId(fresh, "skill-editor-frozen").length, 0);
  act(() => fresh.unmount());

  const edit = await createAsync(createElement(SkillEditorPage, { ...props, skillId: "sk_1" }));
  await tick();
  includesAll(text(edit.root), ["← Skill", "Editing created draft v2 from v1."]);
  assert.equal(byTestId(edit, "skill-editor-submit").length, 1);
  act(() => edit.unmount());

  const frozen = server((call) => (call.url.endsWith("/skills/sk_1")
    ? { status: 200, body: skillDetail({ open: skillVersion("in_review") }) } : { status: 200, body: {} }));
  const { SkillEditorPage: Frozen } = load("admin/components/skillCatalog/SkillEditorPage.tsx", { fetch: frozen.fetch });
  const review = await createAsync(createElement(Frozen, { ...props, skillId: "sk_1" }));
  await tick();
  includesAll(text(review.root), ["v2 is in review and frozen; reject it in the review to change it.", "Back", "Open review"]);
  assert.equal(byTestId(review, "skill-editor-frozen").length, 1);
  assert.equal(byTestId(review, "skill-editor-save").length, 0);
  act(() => review.unmount());
});

const source = (patch = {}) => ({
  id: "src1", kind: "git", label: "Team skills", trust: "official", url: "https://git.example/skills", ref: "main", base_path: "skills",
  named_connection_id: null, licence_detected: "MIT", last_checked_at: null, last_seen_commit: "abcdef1234567", last_error: null, skills: 2, ...patch,
});
const skillRow = (patch = {}) => ({
  id: "s1", name: "lint", kind: "skill", tags: [], description: "", category: null, published: null, open: null,
  available: { platform_chat: true, octryx_claude: true }, source: { id: "src1", kind: "git", label: "Team skills" },
  tracking_mode: "follow", update_available: true, upstream_status: null, uses: 0, workspaces: 0, ...patch,
});

test("the sources tab lists upstream sources with their status and the uploads row", async () => {
  const settings = { licence_allowlist: [], allowed_hosts: [], update_check_hours: 24, always_allowed_licences: [] };
  const srv = server((call) => (call.url.endsWith("/sources") ? { status: 200, body: { sources: [source()], settings } } : { status: 200, body: {} }));
  const { SkillSourcesTab } = load("admin/components/skillCatalog/SkillSourcesTab.tsx", { fetch: srv.fetch });
  const rows = [skillRow(), skillRow({ id: "s2", name: "notes", source: null, update_available: false, tracking_mode: null })];
  const view = await createAsync(createElement(SkillSourcesTab, { rows, onChanged() {}, onOpenSkill() {}, onReviewUpdate() {} }));
  await tick();
  includesAll(text(view.root), ["Team skills", "https://git.example/skills", "main", "MIT", "Check all now", "Check now", "Edit"]);
  assert.deepEqual(all(view, "th").map((node) => text(node)).slice(0, 7), ["Source", "Ref / path", "Licence", "Skills", "Tracking", "Last check", "Status"]);
  assert.equal(byTestId(view, "source-row-src1").length, 1);
  assert.equal(byTestId(view, "source-update-lint").length, 1);
  assert.equal(text(byTestId(view, "source-update-lint")[0]), "Update available");
  act(() => view.unmount());
});

const template = (scope_type, scope_id, versions) => ({ id: `t-${scope_type}`, key: "chat.system", scope_type, scope_id, scope_key: scope_id ?? "global", versions });
const promptVersion = (id, version, state) => ({
  id, version, state, source: "admin", digest: `sha256:${id}`, change_note: "tighter", created_by: "u1", created_at: null,
  approval_id: null, published_by: null, published_at: null, retired_at: null, body: `Body ${id}`,
});

test("a prompt's detail drawer shows the text in use, the versions by scope and the shipped text", () => {
  const { PromptDetailDrawer } = load("admin/components/promptCatalog/PromptDetailDrawer.tsx");
  const detail = {
    key: "chat.system", area: "chat", title: "Chat system prompt", description: "The base text", risk: "high",
    placeholders: ["name"], placeholder_descriptions: { name: "The user's name" }, seed: "Seed text {name}", seed_digest: "sha256:0123456789abcdefghij",
    templates: [template("global", null, [promptVersion("g1", 1, "published"), promptVersion("g2", 2, "draft")])],
    writable_scopes: [{ scope_type: "global", scope_id: null, label: "Global" }],
  };
  const model = { detail, busy: null, notice: "Saved.", refusal: null, diff: null, clearDiff() {}, clearMessages() {}, revert: async () => {} };
  let view;
  act(() => { view = TestRenderer.create(createElement(PromptDetailDrawer, { model, initialScope: null, onNewDraft() {}, onClose() {} })); });
  includesAll(text(view.root), ["Chat system prompt", "The base text", "Placeholders", "Text in use", "Saved.",
    "A run without its own workflow or Workspace text uses", "(v1).", "New draft for global…", "Versions by scope", "Shipped text",
    "sha256:0123456789ab…", "Served when no reviewed override is published.", "Seed text {name}"]);
  assert.equal(byTestId(view, "pc-versions").length, 1);
  assert.equal(all(view, "tr").length, 3);
  assert.equal(byTestId(view, "pc-version").length, 0);
  const viewButtons = all(view, "button").filter((node) => text(node) === "View");
  assert.equal(viewButtons.length, 2);
  act(() => viewButtons[1].props.onClick());
  assert.equal(byTestId(view, "pc-version").length, 1);
  includesAll(text(byTestId(view, "pc-version")[0]), ["v2", "sha256:g2", "tighter", "Body g2"]);
  act(() => view.unmount());

  let loading;
  act(() => { loading = TestRenderer.create(createElement(PromptDetailDrawer, { model: { ...model, detail: null, busy: "load", notice: null }, initialScope: null, onNewDraft() {}, onClose() {} })); });
  assert.ok(text(loading.root).includes("Loading prompt…"));
  act(() => loading.unmount());
});

const runRow = (patch = {}) => ({
  run_key: "rk1", session_id: "s1", time: "2026-01-01T10:00:00Z", started_at: null, duration_ms: 1500, workspace_id: "w1",
  workspace_name: "Core", user_id: "u1", user_name: "Ada", agent_label: "Fixer", source: "chat", outcome: "ok", steps: 2,
  tool_count: 1, tool_failed: 0, cost: 0.12, cost_state: "priced", ...patch,
});

test("the runs page shows the toolbar, one row per run and the paging line", async () => {
  const calls = [];
  const readJson = async (url) => {
    calls.push(url);
    if (url.includes("/observability/runs?") || url.startsWith("/api/v1/observability/runs?")) {
      return { window_hours: 24, page: 1, page_size: 50, total: 2, total_in_window: 5, items: [runRow(), runRow({ run_key: "rk2", cost_state: "unpriced", workspace_name: null })] };
    }
    return { items: [], total: 0 };
  };
  const { ObservabilityRunsPage } = load("admin/components/observability/ObservabilityRunsPage.tsx");
  const view = await createAsync(createElement(ObservabilityRunsPage, { projects: [{ id: "w1", name: "Core" }], readJson }));
  await tick(5);
  const page = text(view.root);
  includesAll(page, ["All sources", "All outcomes", "Refresh", "Core", "Ada", "Fixer", "No Workspace", "! Unpriced", "Page 1 of 1", "Previous", "Next"]);
  assert.deepEqual(all(view, "th").map((node) => text(node)).slice(-8), ["Time", "Workspace · user", "Agent / workflow", "Source", "Outcome", "Tools", "Duration", "Cost"]);
  assert.equal(view.root.findAll((node) => node.type === "tr" && node.props.className === "ob-row-button").length, 2);
  assert.equal(byTestId(view, "observability-runs").length, 1);
  act(() => view.unmount());
});

test("the run drawer shows the facts, the steps, the decisions, the cost and the hidden content", async () => {
  const detail = {
    run_key: "rk1", session_id: "s1", source: "chat", workspace_id: "w1", workspace_name: "Core", user_id: "u1", user_name: "Ada",
    viewer_is_owner: false, agent_label: "Fixer", outcome: "blocked", started_at: "2026-01-01T10:00:00Z", ended_at: "2026-01-01T10:00:05Z",
    steps: [{ time: "2026-01-01T10:00:01Z", kind: "model", provider: "p", model: "m1", tokens_in: 10, tokens_out: 5, outcome: "ok", gate: null },
      { time: "2026-01-01T10:00:02Z", kind: "gate", provider: "", model: "", tokens_in: 0, tokens_out: 0, outcome: "blocked", gate: { gate: "dlp", label: "Data", status: "blocked_hard", reason: "secret" } }],
    steps_truncated: false, tools: [{ tool: "search", status: "success", duration_ms: 200, time: "2026-01-01T10:00:03Z" }],
    cost: { total: 0.5, state: "priced", by_model: [{ model: "m1", state: "priced", calls: 2, cost: 0.5 }] }, effective_setup: { a: 1 },
  };
  const readJson = async () => detail;
  const { RunDrawer } = load("admin/components/observability/RunDrawer.tsx");
  const view = await createAsync(createElement(RunDrawer, { runKey: "rk1", readJson, onClose() {} }));
  includesAll(text(view.root), ["Workspace", "Core", "User", "Ada", "Outcome", "Cost", "Steps", "Model call · m1 · 10 in / 5 out",
    "Data: blocked_hard (secret)", "Tool · search", "Decisions in this run", "Blocked hard", "Data: secret", "m1 · 2 calls",
    "Content", "Show content (audited)", "Effective setup", "Owner only", "Close"]);
  assert.equal(view.root.findAll((node) => node.props.className === "ob-step").length, 3);
  assert.equal(all(view, "h3").length, 4);
  const setup = all(view, "button").find((node) => text(node) === "Effective setup");
  act(() => setup.props.onClick());
  assert.equal(all(view, "h3").length, 5);
  act(() => view.unmount());
});

test("a plugin frame loads its view into a sandboxed iframe, or says why it failed", async () => {
  const MutationObserver = class { observe() {} disconnect() {} };
  const view = { base_url: "https://plugin.example/ui/", token: "t", methods: ["read"], slots: [] };
  const ok = async () => view;
  const { PluginFrame } = load("admin/components/plugins/PluginFrame.tsx", { MutationObserver,
    window: { setTimeout: () => 0, clearTimeout: () => {}, addEventListener: () => {}, removeEventListener: () => {} } });
  const props = { install: { id: "i1", name: "Board", scope: "workspace" }, slot: { id: "main", entry: "index.html" }, title: "Board",
    workspaceId: "w1", viewer: { id: "u1", name: "Ada", role: "admin" } };
  const frame = await createAsync(createElement(PluginFrame, { ...props, fetcher: ok }));
  assert.equal(byTestId(frame, "plugin-frame").length, 1);
  const iframes = all(frame, "iframe");
  assert.equal(iframes.length, 1);
  assert.equal(iframes[0].props.sandbox, "allow-scripts allow-forms");
  assert.equal(iframes[0].props.title, "Board");
  act(() => frame.unmount());

  const failing = async () => { throw Object.assign(new Error("Not found"), { status: 404 }); };
  const failed = await createAsync(createElement(PluginFrame, { ...props, fetcher: failing, compact: true }));
  assert.equal(byTestId(failed, "plugin-frame-failed").length, 1);
  act(() => failed.unmount());
});

test("the hand-written Cedar editor shows its toolbar, the note, the diff toggle and the live line", () => {
  const { CedarSetEditor } = load("admin/components/policyEngine/CedarSetEditor.tsx");
  const Editor = (props) => createElement("textarea", { "data-testid": "editor", value: props.value, readOnly: props.readOnly });
  const published = { version: 3, state: "published", policies: "forbid(principal, action, resource);", note: "", digest: "d3", testReport: null };
  const working = { version: 4, state: "draft", policies: "forbid(principal, action, resource);\n// more", note: "Draft note", digest: "d4", testReport: null };
  let view;
  act(() => { view = TestRenderer.create(createElement(CedarSetEditor, { editor: Editor, schema: "", published, working, onBack() {}, onChanged: async () => {} })); });
  includesAll(text(view.root), ["← Policies", "Hand-written Cedar", "Version 4", "Validate", "Save to draft", "Published: version 3.",
    "Change note", "Compare with the published version (+0 / −0 lines)", "Live validation is not available in this browser"]);
  assert.equal(byTestId(view, "cedar-note")[0].props.value, "Draft note");
  assert.equal(byTestId(view, "cedar-save")[0].props.disabled, true);
  assert.equal(byTestId(view, "editor").length, 1);
  assert.equal(byTestId(view, "cedar-conflict").length, 0);
  act(() => view.unmount());

  let frozen;
  act(() => { frozen = TestRenderer.create(createElement(CedarSetEditor, { editor: Editor, schema: "", published: null, working: { ...working, state: "in_review" }, onBack() {}, onChanged: async () => {} })); });
  includesAll(text(frozen.root), ["Published: none.", "This version is in review: its text is frozen."]);
  act(() => frozen.unmount());
});

test("the knowledge packages panel shows the research form, the package tabs and the selected package", async () => {
  const pkg = { id: "k1", title: "Spring 4", product: "spring", versions: ["4.0"], state: "proposed",
    research: { rounds: [{ queries: ["spring 4 upgrade"], search_outcomes: ["ok", "ok"] }] }, documents: [], held_untrusted: [], counts: null };
  const srv = server((call) => (call.url.includes("/packages") ? { status: 200, body: { packages: [pkg] } } : { status: 200, body: {} }));
  const { KnowledgePackagesPanel } = load("admin/components/workspaceKnowledge/KnowledgePackagesPanel.tsx", { fetch: srv.fetch });
  const view = await createAsync(createElement(KnowledgePackagesPanel, { workspaceId: "w1" }));
  await tick();
  includesAll(text(view.root), ["Let an agent research a package", "Research", "Spring 4 · proposed", "spring 4.0 · proposed",
    "1 research round · last queries: spring 4 upgrade · search: ok", "Commission further research", "Research more",
    "then extract into the knowledge graph", "Approve & ingest accepted sources"]);
  assert.equal(all(view, "form").length, 2);
  assert.equal(all(view, "input").length, 8);
  act(() => view.unmount());
});
