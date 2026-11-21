// Render guards for admin form sections split into smaller functions: the Bedrock prompt caching row, the scheduler
// form panel, the code repositories section, the research evidence archive, the Workspace skills picker and the
// Confluence scope fields render the same structure.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import { act, byTestId, text } from "./settingsRenderHarness.mjs";
import { all, buttons, create, includesAll, noop, plain, testIds } from "./adminGuardRenderers.mjs";
import { loadStubbed, stubs } from "./adminGuardStubLoader.mjs";

test("the Bedrock prompt caching row edits the credentials and the cache and saves them", () => {
  const { ProviderBedrockPromptCaching } = loadStubbed("admin/components/providerTab/ProviderBedrockPromptCaching.tsx", []);
  const changes = [];
  const saved = [];
  const ctx = { handleProviderDraftChange: (...args) => changes.push(args), handleSaveBedrockProviderConfig: (p) => saved.push(p.id),
    providerDrafts: { p1: { aws_access_key_id: "AK", bedrock_prompt_cache_enabled: "true", bedrock_prompt_cache_min_tokens: "1024" } },
    savingProviderConfig: null };
  const view = create(createElement(ProviderBedrockPromptCaching, { ctx, provider: { id: "p1", aws_static_credentials_configured: true } }));
  includesAll(text(view.root), ["Bedrock", "Static credentials: Configured", "Bedrock cache enabled", "TTL: 5 minutes", "TTL: 1 hour", "Save Bedrock Config"]);
  assert.deepEqual(all(view, "input").map((node) => [node.props.type ?? "text", node.props.placeholder ?? null, node.props.value ?? node.props.checked]), [
    ["text", "AWS Access Key ID", "AK"], ["password", "AWS Secret Access Key", ""], ["password", "AWS Session Token (optional)", ""],
    ["checkbox", null, true], ["number", "Min tokens", "1024"]]);
  assert.equal(all(view, "select")[0].props.value, "5m");
  const inputs = all(view, "input");
  for (const [index, value] of [[0, "a"], [1, "b"], [2, "c"], [4, "9"]]) inputs[index].props.onChange({ target: { value } });
  inputs[3].props.onChange({ target: { checked: false } });
  all(view, "select")[0].props.onChange({ target: { value: "1h" } });
  assert.deepEqual(changes, [["p1", "aws_access_key_id", "a"], ["p1", "aws_secret_access_key", "b"], ["p1", "aws_session_token", "c"],
    ["p1", "bedrock_prompt_cache_min_tokens", "9"], ["p1", "bedrock_prompt_cache_enabled", "false"], ["p1", "bedrock_prompt_cache_ttl", "1h"]]);
  all(view, "button")[0].props.onClick();
  assert.deepEqual(saved, ["p1"]);
  const saving = create(createElement(ProviderBedrockPromptCaching, { ctx: { ...ctx, providerDrafts: {}, savingProviderConfig: "p1" }, provider: { id: "p1" } }));
  includesAll(text(saving.root), ["Static credentials: Not set", "Saving…"]);
  assert.equal(all(saving, "button")[0].props.disabled, true);
  assert.equal(all(saving, "input")[3].props.checked, false);
});

test("the scheduler form panel shows the fields, the action list and the right hint", () => {
  const { SchedulerFormPanel } = loadStubbed("admin/components/scheduler/SchedulerFormPanel.tsx",
    ["/SidePanel", "./SchedulerNextRunsPreview", "./SchedulerScheduleFields"]);
  const set = [];
  const submitted = [];
  const props = { tasks: [{ id: "t1", name: "Nightly" }, { id: "t2", name: "Weekly" }], editingScheduler: null, schedulerFormName: "Night",
    setSchedulerFormName: (value) => set.push(["name", value]), schedulerFormDesc: "", setSchedulerFormDesc: (value) => set.push(["desc", value]),
    schedulerFormCron: "0 1 * * *", setSchedulerFormCron: noop, schedulerFormTaskId: "t1", setSchedulerFormTaskId: (value) => set.push(["task", value]),
    schedulerFormLoading: false, schedulerFormError: null, onCloseSchedulerForm: noop, onSaveScheduler: (event, preview) => submitted.push(preview),
    preview: { state: "ok" }, retry: noop, gate: { canSubmit: true, blocker: null }, chosenAction: { id: "t1", name: "Nightly" } };
  const view = create(createElement(SchedulerFormPanel, props));
  const panel = stubs(view, "SidePanel")[0];
  assert.deepEqual([panel.props.title, panel.props.testId], ["New scheduler", "scheduler-panel"]);
  includesAll(text(view.root), ["Scheduler name *", "Description", "Action *", "Select action…", "Nightly", "Weekly", "Cancel", "Create and activate",
    "Creating activates this scheduler: it runs the action \"Nightly\" at the times shown."]);
  assert.equal(stubs(view, "SchedulerScheduleFields")[0].props.value, "0 1 * * *");
  assert.equal(stubs(view, "SchedulerNextRunsPreview").length, 1);
  assert.equal(all(view, "option").length, 3);
  all(view, "input")[0].props.onChange({ target: { value: "A" } });
  all(view, "input")[1].props.onChange({ target: { value: "B" } });
  all(view, "select")[0].props.onChange({ target: { value: "t2" } });
  all(view, "form")[0].props.onSubmit({});
  assert.deepEqual(set, [["name", "A"], ["desc", "B"], ["task", "t2"]]);
  assert.deepEqual(plain(submitted), [{ state: "ok" }]);

  const edit = create(createElement(SchedulerFormPanel, { ...props, editingScheduler: { id: "s1", name: "Night", is_active: false },
    gate: { canSubmit: false, blocker: "Pick a time." } }));
  assert.equal(stubs(edit, "SidePanel")[0].props.title, "Edit Night");
  includesAll(text(edit.root), ["Save changes", "Saving keeps this scheduler paused; use Pause or Resume to change that.", "Pick a time."]);
  assert.equal(all(edit, "button")[1].props.disabled, true);
  const failed = create(createElement(SchedulerFormPanel, { ...props, chosenAction: undefined, schedulerFormError: "Boom", schedulerFormLoading: true }));
  includesAll(text(failed.root), ["Saving…", "Creating activates this scheduler. Choose the action it runs.", "Boom"]);
});

test("the code repositories section lists the cards and passes the form its fields", () => {
  const { CodeRepositoriesSection } = loadStubbed("admin/components/projectCodeSync/CodeRepositoriesSection.tsx", ["./CodeRepositoryCard", "./CodeRepositoryForm"]);
  const keys = ["editingProjectCodeRepositoryId", "handleDeleteProjectCodeRepository", "handleEditProjectCodeRepository", "handleRunProjectCodeIndex",
    "handleSaveProjectCodeRepository", "projectCodeRepositoryActive", "projectCodeRepositoryBranch", "projectCodeRepositoryDescription",
    "projectCodeRepositoryGraphBackend", "projectCodeRepositoryIndexBackend", "projectCodeRepositoryLoading", "projectCodeRepositoryName",
    "projectCodeRepositoryProvider", "projectCodeRepositoryRemoteUrl", "projectCodeRepositoryRoot", "projectCodeRepositoryRunningId",
    "projectCodeRepositorySemanticBackend", "projectCodeRepositoryStructureBackend", "resetProjectCodeRepositoryForm", "setProjectCodeRepositoryActive",
    "setProjectCodeRepositoryBranch", "setProjectCodeRepositoryDescription", "setProjectCodeRepositoryGraphBackend", "setProjectCodeRepositoryIndexBackend",
    "setProjectCodeRepositoryName", "setProjectCodeRepositoryProvider", "setProjectCodeRepositoryRemoteUrl", "setProjectCodeRepositoryRoot",
    "setProjectCodeRepositorySemanticBackend", "setProjectCodeRepositoryStructureBackend"];
  const props = Object.fromEntries(keys.map((key) => [key, `value:${key}`]));
  props.configuringProjectQuality = { code_repositories: [{ id: "r1" }, { id: "r2" }] };
  const view = create(createElement(CodeRepositoriesSection, { props }));
  includesAll(text(view.root), ["Code Intelligence Repositories (2)", "Register coding repositories per project"]);
  const cards = stubs(view, "CodeRepositoryCard");
  assert.deepEqual(cards.map((node) => node.props.repo.id), ["r1", "r2"]);
  assert.deepEqual(Object.keys(cards[0].props).filter((key) => key !== "children").sort(), ["handleDeleteProjectCodeRepository", "handleEditProjectCodeRepository",
    "handleRunProjectCodeIndex", "projectCodeRepositoryLoading", "projectCodeRepositoryRunningId", "repo"]);
  const form = stubs(view, "CodeRepositoryForm")[0].props;
  const passed = keys.filter((key) => !["handleDeleteProjectCodeRepository", "handleEditProjectCodeRepository", "handleRunProjectCodeIndex",
    "projectCodeRepositoryRunningId"].includes(key));
  assert.deepEqual(Object.keys(form).filter((key) => key !== "children").sort(), passed.sort());
  for (const key of passed) assert.equal(form[key], `value:${key}`, key);
  const empty = create(createElement(CodeRepositoriesSection, { props: { ...props, configuringProjectQuality: {} } }));
  assert.ok(text(empty.root).includes("Code Intelligence Repositories (0)"));
});

test("the evidence archive section previews the folders and toggles the archive switches", () => {
  const { ResearchPolicyArchiveSection } = loadStubbed("admin/components/researchPolicies/ResearchPolicyArchiveSection.tsx", []);
  const paths = [];
  const spec = { evidence_archive: { preserve_parsed_text: false } };
  const view = create(createElement(ResearchPolicyArchiveSection, { spec, archiveFolder: "/arch", setPath: (path, value) => paths.push([path, value]) }));
  includesAll(text(view.root), ["Evidence archive", "deterministic source folder tree", "/arch/<bundle>/sources/<source-id-title>/raw",
    "/arch/<bundle>/sources/<source-id-title>/parsed", "/arch/<bundle>/sources/<source-id-title>/evidence", "evidence_manifest.json",
    "Preserve raw sources", "Preserve parsed text", "Write source manifests", "Write bundle manifest"]);
  assert.equal(all(view, "code").length, 4);
  assert.deepEqual(all(view, "input").map((node) => node.props.checked), [true, false, true, true]);
  all(view, "input").forEach((node, index) => node.props.onChange({ target: { checked: index % 2 === 0 } }));
  assert.deepEqual(plain(paths), [[["evidence_archive", "preserve_raw_sources"], true], [["evidence_archive", "preserve_parsed_text"], false],
    [["evidence_archive", "write_source_manifests"], true], [["evidence_archive", "write_bundle_manifest"], false]]);
});

const node = (id, key, label, children = [], archived = false) => ({ id, key, label, description: "", parent_id: null, sort_order: 0, archived, skills: 0, children });
const skill = (id, name, category_key, kind = "skill") => ({ id, name, kind, description: `${name} help`, version: 1, category_key, category_path: [] });

test("the Workspace skills picker shows the modes and the category and skill tree", () => {
  const { WorkspaceSkillsPicker } = loadStubbed("admin/components/projectsTab/WorkspaceSkillsPicker.tsx", []);
  const changes = [];
  const categories = [node("c1", "qa", "QA", [node("c2", "qa.lint", "Lint"), node("c4", "qa.old", "Old", [], true)]), node("c3", "empty", "Empty")];
  const skills = [skill("s1", "tester", "qa"), skill("s2", "linter", "qa.lint", "mcp_server"), skill("s3", "loose", null)];
  const draft = { mode: "selected_only", skill_ids: ["s3"], category_keys: ["qa"], blocked_skill_ids: ["s2"], surfaces: {} };
  const view = create(createElement(WorkspaceSkillsPicker, { draft, categories, skills, disabled: false, onChange: (next) => changes.push(next) }));
  includesAll(text(view.root), ["All published", "Selected categories and skills", "None", "Tick a category to assign all", "QA", "whole category",
    "tester", "Lint", "linter", "MCP", "Empty", "Other", "loose", "Block"]);
  assert.deepEqual(testIds(view), ["ws-mode", "ws-mode-all_active", "ws-mode-selected_only", "ws-mode-none", "ws-picker", "ws-category-qa",
    "ws-skill-tester", "ws-block-tester", "ws-category-qa.lint", "ws-skill-linter", "ws-block-linter", "ws-category-qa.old", "ws-category-empty", "ws-skill-loose", "ws-block-loose"]);
  assert.equal(byTestId(view, "ws-mode-selected_only")[0].props["aria-pressed"], true);
  assert.equal(byTestId(view, "ws-category-qa.lint")[0].findByType("input").props.disabled, true);
  act(() => byTestId(view, "ws-block-tester")[0].props.onChange());
  act(() => byTestId(view, "ws-mode-none")[0].props.onClick());
  act(() => byTestId(view, "ws-category-empty")[0].findByType("input").props.onChange());
  assert.deepEqual(changes.map((next) => [next.mode, next.blocked_skill_ids.length, next.category_keys.length]),
    [["selected_only", 2, 1], ["none", 1, 1], ["selected_only", 1, 2]]);

  const all_ = create(createElement(WorkspaceSkillsPicker, { draft: { ...draft, mode: "all_active" }, categories, skills, disabled: true, onChange: noop }));
  includesAll(text(all_.root), ["Every published skill is assigned."]);
  assert.deepEqual(testIds(all_).filter((id) => id.startsWith("ws-category")), []);
  assert.ok(!text(all_.root).includes("Empty"));
  const none = create(createElement(WorkspaceSkillsPicker, { draft: { ...draft, mode: "none" }, categories, skills, disabled: false, onChange: noop }));
  assert.equal(byTestId(none, "ws-picker").length, 0);
  const bare = create(createElement(WorkspaceSkillsPicker, { draft: { ...draft, mode: "all_active" }, categories: [], skills: [], disabled: false, onChange: noop }));
  assert.ok(text(bare.root).includes("No published skills in the catalog yet."));
});

test("the Confluence scope fields switch between whole spaces and page trees", () => {
  const { KnowledgeConfluenceScopeFields } = loadStubbed("admin/components/workspaceKnowledge/KnowledgeConfluenceScopeFields.tsx", []);
  const patches = [];
  const spaceKeysInput = createElement("input", { "data-testid": "space-keys" });
  const form = { scopeMode: "spaces", keys: "", pageTrees: [{ space_key: "ENG", root_page_id: "11" }] };
  const spaces = create(createElement(KnowledgeConfluenceScopeFields, { form, set: (patch) => patches.push(patch), spaceKeysInput }));
  includesAll(text(spaces.root), ["Whole spaces", "Page trees (a page and every page below it)", "Saving with whole spaces removes the 1 page tree of this connector."]);
  assert.deepEqual(testIds(spaces), ["space-keys", "page-trees-dropped"]);
  all(spaces, "input")[1].props.onChange();
  assert.deepEqual(plain(patches), [{ scopeMode: "trees" }]);

  const trees = create(createElement(KnowledgeConfluenceScopeFields, { form: { ...form, scopeMode: "trees" }, set: (patch) => patches.push(patch), spaceKeysInput }));
  includesAll(text(trees.root), ["Space ENG · root page 11 and every page below it", "Remove"]);
  assert.deepEqual(testIds(trees), ["page-tree-list"]);
  const address = () => trees.root.find((n) => n.props["aria-label"] === "Root page address");
  act(() => address().props.onChange({ target: { value: "nonsense" } }));
  assert.equal(byTestId(trees, "page-address-problem").length, 1);
  act(() => address().props.onChange({ target: { value: "https://x.atlassian.net/wiki/spaces/OPS/pages/22/Title" } }));
  includesAll(text(byTestId(trees, "page-address-read")[0]), ["page id 22", "in space OPS", "Add page tree"]);
  act(() => all(trees, "button").find((n) => text(n) === "Add page tree").props.onClick());
  assert.deepEqual(plain(patches.at(-1)), { pageTrees: [{ space_key: "ENG", root_page_id: "11" }, { space_key: "OPS", root_page_id: "22" }] });
  assert.equal(address().props.value, "");
  act(() => address().props.onChange({ target: { value: "https://x.atlassian.net/wiki/spaces/ENG/pages/11/T" } }));
  assert.ok(text(trees.root).includes("This root page is already listed."));
  all(trees, "button")[0].props.onClick();
  assert.deepEqual(plain(patches.at(-1)), { pageTrees: [] });
  trees.root.find((n) => n.props["aria-label"] === "Whole spaces too").props.onChange({ target: { value: "A" } });
  assert.deepEqual(plain(patches.at(-1)), { keys: "A" });
  const emptyTrees = create(createElement(KnowledgeConfluenceScopeFields, { form: { ...form, scopeMode: "trees", pageTrees: [] }, set: noop, spaceKeysInput }));
  assert.ok(text(emptyTrees.root).includes("No page tree yet: paste the address of a root page."));
  assert.deepEqual(buttons(emptyTrees), []);
});
