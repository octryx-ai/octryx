// Render guards for the Workspace settings sections, the research literature section, the code repository form and
// the skill update review: each renders with representative props and keeps its key labels, controls and rows.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";

import { act, byTestId, load, server, text, tick } from "./settingsRenderHarness.mjs";

const noop = () => {};
const ok = (body) => ({ status: 200, body });

async function mount(relative, exportName, props, answer = () => ok({})) {
  const srv = server(answer);
  const module = load(relative, { fetch: srv.fetch });
  let view;
  await act(async () => { view = TestRenderer.create(createElement(module[exportName], props)); });
  await tick();
  return view;
}

const ofType = (view, type) => view.root.findAllByType(type);
const labels = (view) => ofType(view, "label").map(text);
const buttons = (view) => ofType(view, "button").map(text);

test("research literature section: two selects, five toggles, four lists and the no-policy hint", async () => {
  const view = await mount("admin/components/researchPolicies/ResearchPolicyLiteratureSection.tsx", "ResearchPolicyLiteratureSection", {
    spec: { source_policy: { literature_policy: { mode: "auto", preferred_domains: ["arxiv.org", "nature.com"] } } },
    literaturePolicy: null, setPath: noop, setListPath: noop,
  });
  assert.equal(ofType(view, "select").length, 2);
  assert.equal(ofType(view, "input").filter((node) => node.props.type === "checkbox").length, 5);
  assert.equal(ofType(view, "textarea").length, 4);
  assert.equal(ofType(view, "textarea")[0].props.value, "arxiv.org\nnature.com");
  const all = labels(view).join("|");
  for (const label of ["Enable literature policy", "Published only", "Peer-reviewed only", "Exclude preprints/drafts",
    "Restrict to preferred domains", "Preferred databases", "Excluded publication types"]) assert.match(all, new RegExp(label));
  assert.match(text(view.toJSON()), /No literature policy exists yet/);
});

test("workspace voice section: header, both switches and the save button", async () => {
  const readJson = async (url) => (url.includes("/tts/providers")
    ? { providers: [{ id: "openai", name: "OpenAI", voices: ["alloy", "echo"], has_key: true, installed: true }] }
    : { id: "ws-1", name: "Alpha", config: { tts: { enabled: true, provider: "openai", default_voice: "echo" }, stt: { enabled: false } } });
  const view = await mount("admin/components/projectsTab/ProjectVoiceSection.tsx", "ProjectVoiceSection", {
    ctx: { configuringProjectQuality: { id: "ws-1", name: "Alpha" }, readJson },
  });
  await tick();
  const switches = view.root.findAll((node) => node.props.role === "switch" && typeof node.type === "string");
  assert.equal(switches.length, 2);
  assert.deepEqual(switches.map((node) => node.props["aria-checked"]), [true, false]);
  const all = text(view.toJSON());
  for (const part of ["Voice configuration", "Alpha", "Text-to-Speech (TTS)", "Speech-to-Text (STT)",
    "Active — agents can synthesize speech for this project"]) assert.ok(all.includes(part), part);
  assert.deepEqual(buttons(view).filter((label) => /Voice/.test(label)), ["Open Runtime → Voice", "Save Voice Settings"]);
});

test("repository bootstrap form: GitHub fields, both toggles and both actions", async () => {
  const set = noop;
  const view = await mount("admin/components/projectsTab/policies/ProjectRepositoryBootstrapForm.tsx", "ProjectRepositoryBootstrapForm", {
    projectRepoBootstrapProvider: "github", setProjectRepoBootstrapProvider: set, projectRepoBootstrapDefaultBranch: "main",
    setProjectRepoBootstrapDefaultBranch: set, projectRepoBootstrapDefaultRepoName: "svc", setProjectRepoBootstrapDefaultRepoName: set,
    projectRepoBootstrapWorkspaceSubdir: "repo", setProjectRepoBootstrapWorkspaceSubdir: set, projectRepoBootstrapRemoteVisibility: "private",
    setProjectRepoBootstrapRemoteVisibility: set, projectRepoBootstrapGithubOwner: "acme", setProjectRepoBootstrapGithubOwner: set,
    projectRepoBootstrapGithubOwnerType: "org", setProjectRepoBootstrapGithubOwnerType: set, projectRepoBootstrapBitbucketProjectKey: "",
    setProjectRepoBootstrapBitbucketProjectKey: set, projectRepoBootstrapEnabled: true, setProjectRepoBootstrapEnabled: set,
    projectRepoBootstrapAutoOnSessionStart: false, setProjectRepoBootstrapAutoOnSessionStart: set, projectQualityLoading: false,
    onSubmit: noop, onUseImplicitLocalFallback: noop,
  });
  assert.deepEqual(labels(view), ["Provider", "Default branch", "Default repo name", "Project checkout subdir", "Remote visibility",
    "GitHub owner", "GitHub owner type"]);
  const all = text(view.toJSON());
  assert.ok(all.includes("Bootstrap enabled") && all.includes("Bootstrap on first write"));
  assert.deepEqual(buttons(view), ["", "", "Save Repository Bootstrap", "Use Implicit Local Fallback"]);
});

test("capability binding card: badges, six fields and the save action", async () => {
  const binding = {
    id: "b-1", binding_key: "docs", display_name: "Docs", binding_status: "active", is_enabled: true, is_default: true,
    intent_scopes: ["documentation"], binding_config: { a: 1 }, policy_config: {}, capability_kind: "knowledge",
    source_entity_type: "connector", capability_type: { key: "kb", name: "Knowledge base", description: "Searches docs", lifecycle_status: "ga" },
  };
  const view = await mount("admin/components/projectsTab/workspaceComposition/WorkspaceCapabilityBindingCard.tsx",
    "WorkspaceCapabilityBindingCard", { binding, isSaving: false, onSave: async () => {} });
  const all = text(view.toJSON());
  for (const part of ["Knowledge base", "knowledge", "kb", "default", "Enabled", "Searches docs", "Default for knowledge",
    "source: connector", "lifecycle: ga"]) assert.ok(all.includes(part), part);
  assert.equal(ofType(view, "textarea").length, 3);
  assert.equal(ofType(view, "input").length, 3);
  assert.deepEqual(buttons(view), ["Save assignment"]);
});

test("workflow proposal section: stored policy, the switch and the revocable tool approvals", async () => {
  const config = {
    workflow_proposal_policy: { enabled: true },
    standing_tool_approvals: { rules: [{ tool_name: "bash", argument_class: "read", granted_by: "ana" }] },
  };
  const view = await mount("admin/components/projectsTab/ProjectWorkflowProposalSection.tsx", "ProjectWorkflowProposalSection",
    { ctx: { configuringProjectQuality: { id: "ws-1", name: "Alpha" } } }, () => ok({ config }));
  await tick();
  assert.equal(byTestId(view, "proposal-policy-stored").length, 1);
  const radios = ofType(view, "input").filter((node) => node.props.type === "radio");
  assert.equal(radios.length, 3);
  const lists = view.root.findAll((node) => node.type === "ul");
  assert.deepEqual(lists.map((node) => node.props["aria-label"]), ["Standing tool approvals"]);
  assert.equal(buttons(view).filter((label) => label === "Revoke").length, 1);
  assert.ok(buttons(view).includes("Save proposal policy"));
});

test("workspace resources: the repository view and the knowledge view", async () => {
  const payload = {
    repositories: [{ id: "r-1", name: "api", provider: "github", repo_root: "/w/api", operation_policy: { read: true, write: false } }],
    knowledge_base: { project_id: "ws-1", project_name: "Alpha", access: "read" },
    knowledge_access: { mode: "default", default_workspace_access: true },
    knowledge_mounts: [], available_knowledge_bases: [{ project_id: "ws-2", project_name: "Beta" }], policy_keys: ["read", "write"],
  };
  const readJson = async () => payload;
  const repos = await mount("admin/components/projectsTab/ProjectResourcesSection.tsx", "ProjectResourcesSection",
    { ctx: { configuringProjectQuality: { id: "ws-1" }, readJson }, view: "repositories" });
  assert.match(text(repos.toJSON()), /Repository operation policy/);
  assert.match(text(repos.toJSON()), /api/);
  const knowledge = await mount("admin/components/projectsTab/ProjectResourcesSection.tsx", "ProjectResourcesSection",
    { ctx: { configuringProjectQuality: { id: "ws-1" }, readJson }, view: "knowledge" });
  assert.doesNotMatch(text(knowledge.toJSON()), /Repository operation policy/);
  assert.match(text(knowledge.toJSON()), /Beta/);
});

test("code repository form: nine fields, the activity toggle and the edit actions", async () => {
  const set = noop;
  const view = await mount("admin/components/projectCodeSync/CodeRepositoryForm.tsx", "CodeRepositoryForm", {
    handleSaveProjectCodeRepository: async () => {}, projectCodeRepositoryName: "api", setProjectCodeRepositoryName: set,
    projectCodeRepositoryRoot: "/w/api", setProjectCodeRepositoryRoot: set, projectCodeRepositoryProvider: "github",
    setProjectCodeRepositoryProvider: set, projectCodeRepositoryBranch: "main", setProjectCodeRepositoryBranch: set,
    projectCodeRepositoryRemoteUrl: "", setProjectCodeRepositoryRemoteUrl: set, projectCodeRepositoryDescription: "",
    setProjectCodeRepositoryDescription: set, projectCodeRepositoryIndexBackend: "auto", setProjectCodeRepositoryIndexBackend: set,
    projectCodeRepositorySemanticBackend: "auto", setProjectCodeRepositorySemanticBackend: set,
    projectCodeRepositoryStructureBackend: "auto", setProjectCodeRepositoryStructureBackend: set,
    projectCodeRepositoryGraphBackend: "disabled", setProjectCodeRepositoryGraphBackend: set, projectCodeRepositoryActive: true,
    setProjectCodeRepositoryActive: set, projectCodeRepositoryLoading: false, editingProjectCodeRepositoryId: "r-1",
    resetProjectCodeRepositoryForm: noop,
  });
  assert.deepEqual(labels(view), ["Repository name", "Repo root", "Provider", "Default branch", "Remote URL", "Description",
    "Search backend", "Semantic backend", "Structure backend", "Graph backend"]);
  assert.equal(ofType(view, "select").length, 5);
  assert.match(text(view.toJSON()), /Repository active/);
  assert.deepEqual(buttons(view), ["", "Save Code Repository", "Cancel Edit"]);
});

test("skill update review: header, KPIs, the conflict-free note and a diff card", async () => {
  const version = {
    version: 3, state: "draft", digest: "d3",
    security_report: { spec: [], findings: [], summary: { high: 0, medium: 1, info: 2 } },
    merge_report: {
      files: [{ path: "SKILL.md", status: "merged", upstream_hunks: 2, local_hunks: 1 }], conflicts: [], resolutions: {},
      base_commit: "aaaaaaaaaaaa", theirs_commit: "bbbbbbbbbbbb", from_version: 2, path_moved: null,
    },
    files: [{ path: "SKILL.md" }],
  };
  const detail = { id: "s-1", name: "Writer", published: { version: 2 }, open: version, new_findings: [] };
  const answer = (call) => (call.url.includes("/diff")
    ? ok({ files: [{ path: "SKILL.md", status: "modified", added: 1, removed: 1, truncated: false, lines: [{ kind: "removed", text: "old" }, { kind: "added", text: "new" }] }] })
    : call.url.includes("/files") ? ok({ path: "SKILL.md", content: "# Writer" }) : ok(detail));
  const view = await mount("admin/components/skillCatalog/SkillUpdateReview.tsx", "SkillUpdateReview",
    { skillId: "s-1", onBack: noop, onOpenReview: noop, onChanged: noop }, answer);
  await tick();
  assert.equal(byTestId(view, "skill-update-review").length, 1);
  assert.equal(byTestId(view, "skill-update-discard").length, 1);
  assert.equal(byTestId(view, "skill-update-submit").length, 1);
  const all = text(view.toJSON());
  for (const part of ["Update from upstream", "draft v3 · base: published v2", "Upstream changes", "Your local customizations",
    "Security review", "no new risks", "every upstream change merged without a conflict",
    "Changes against published v2 · SKILL.md (+1 / −1)"]) assert.ok(all.includes(part), part);
});
