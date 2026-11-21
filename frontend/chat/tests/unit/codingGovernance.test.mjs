// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/codingGovernance.test.mjs
//
// Coding governance in one place: Effective rules is read only and every
// section links to its one home; quality rules are Delivery pipeline checks; where each setting is edited is page
// help (help/coding/index.md). Requests are stubs; names invented.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { checkDetail } from "../../src/chat/coding/governance/codingRulesApi.ts";
import { codingRuleRows, collapseRows, fileToolsText, globText, ruleText } from "../../src/chat/coding/governance/codingRulesTable.ts";
import { button, byTestId, load, server, text } from "./workCodingSupport.mjs";

const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const RULES = {
  project_id: "ws-1",
  denied: [
    { source: "policy", id: "prod-manifests", title: "Production manifests are reviewed by humans", actions: ["write_path"], detail: "Published policy set v12", edit: "policies", version: 12 },
    { source: "tool_rule", id: "no-env", ids: ["no-env"], title: "path denied: **/.env", actions: ["write_path"], detail: "Workspace tool rule", edit: "policies",
      kind: "path_denied", command: "", argument: "", glob: "**/.env", tools: ["Edit"], origin: "workspace", published_version: null },
  ],
  needs_approval: { items: [{ kind: "tool", value: "merge_pull_request" }], exempt_tools: [], edit: "tool_policies" },
  who_approves: { rule: "four_eyes", edit: "approval_rule" },
  checks: { items: [{ key: "pr", type: "pr_size_threshold", label: "PR size", effect: "review", rule: { max_changed_lines: 600 } }], edit: "delivery_pipeline" },
};

test("a check reads as one line", () => {
  assert.equal(checkDetail({ type: "pr_size_threshold", rule: { max_changed_lines: 600 } }), "More than 600 changed lines");
  assert.equal(checkDetail({ type: "branch_commit_naming", rule: { branch_pattern: "feature/*" } }), "feature/*");
});

// The baseline as the server lists it: parts, origin, and the generated policy folded into its rule.
const TOOL = (id, kind, parts, origin = "baseline", published_version = null) => ({ source: "tool_rule", id, ids: [id],
  title: "raw", actions: [kind.startsWith("command") ? "run_command" : "write_path"], detail: "Workspace tool rule", edit: "policies",
  kind, command: "", argument: "", glob: "", tools: [], origin, published_version, ...parts });
const BASELINE = [
  TOOL("kubectl-requires-context", "command_requires_argument", { command: "kubectl", argument: "--context" }),
  TOOL("no-push-to-main", "command_prefix_denied", { command: "git push origin main" }),
  TOOL("no-force-push", "command_argument_denied", { command: "git push", argument: "--force" }),
  TOOL("no-force-push-short", "command_argument_denied", { command: "git push", argument: "-f" }),
  TOOL("no-env-files", "path_denied", { glob: "**/.env", tools: ["Edit", "MultiEdit", "Read", "Write"] }),
  TOOL("no-aws", "path_denied", { glob: "**/.aws/**", tools: ["Edit", "MultiEdit", "Read", "Write"] }),
  TOOL("no-aws-home", "path_denied", { glob: "~/.aws/**", tools: ["Edit", "MultiEdit", "Read", "Write"] }),
  TOOL("no-pem", "path_denied", { glob: "**/*.pem", tools: ["Edit", "Write"] }, "workspace", 12),
];

test("patterns and commands read as words; nothing raw, the arguments that make two rules differ stay", () => {
  assert.equal(globText("**/.env"), "Any .env file");
  assert.equal(globText("**/.aws/**"), "Anything in an .aws folder");
  assert.equal(globText("~/.aws/**"), "Anything in ~/.aws");
  assert.equal(globText("**/*.pem"), "Any .pem file");
  assert.equal(globText("src/**/gen_*.py"), "src/**/gen_*.py", "an unusual pattern stays as written");
  assert.equal(fileToolsText(["Edit", "Read", "Write"]), "Reading and changing files");
  assert.equal(fileToolsText(["Edit"]), "Changing files");
  const rows = codingRuleRows({ ...RULES, denied: BASELINE });
  const line = (row) => [row.what, ruleText(row.rule), row.appliesTo, row.sources.join(" · ")].join(" | ");
  assert.deepEqual(rows.slice(0, 8).map(line), [
    "Argument required | kubectl only with --context | Commands | Built-in",
    "Command blocked | git push origin main | Commands | Built-in",
    "Argument blocked | git push with --force | Commands | Built-in",
    "Argument blocked | git push with -f | Commands | Built-in",
    "Path blocked | Any .env file | Reading and changing files | Built-in",
    "Path blocked | Anything in an .aws folder | Reading and changing files | Built-in",
    "Path blocked | Anything in ~/.aws | Reading and changing files | Built-in",
    "Path blocked | Any .pem file | Changing files | Workspace · Policy v12",
  ]);
  assert.equal(rows[4].pattern, "**/.env", "the pattern stays at hand (tooltip)");
  assert.doesNotMatch(rows.map(line).join("\n"), /denied|baseline|raw/);
  assert.deepEqual(rows.slice(8).map((row) => row.what), ["Needs approval", "Who approves", "Check"]);
});

test("the same rule from the baseline and the Workspace is one row naming both sources", () => {
  const same = [TOOL("a", "command_prefix_denied", { command: "git push origin main" }),
    TOOL("b", "command_prefix_denied", { command: "git push origin main" }, "workspace"),
    { source: "policy", id: "p", title: "Production manifests", actions: ["write_path"], detail: "Published policy set v12", edit: "policies", version: 12 }];
  const rows = codingRuleRows({ ...RULES, denied: same });
  assert.deepEqual(rows.filter((row) => row.what === "Command blocked").map((row) => row.sources), [["Built-in", "Workspace"]]);
  assert.deepEqual(rows.find((row) => row.key === "policy:p").sources, ["Policy v12"]);
  assert.equal(collapseRows([...rows, ...rows]).length, rows.length);
});

const DOCUMENT = () => ({ getElementById: () => null, addEventListener: () => {}, removeEventListener: () => {}, activeElement: null,
  querySelector: () => null, body: { style: {} } });
const bodyRows = (view) => byTestId(view, "coding-rules-table")[0].findAll((node) => node.type === "tr" && node.props["data-row-key"]);

test("rendered Coding rules: one compact table; a row opens its rule read only with its source and home", async () => {
  const srv = server((url) => (url.endsWith("/admin/workspaces/ws-1/coding") ? { status: 403, body: { detail: "forbidden" } }
    : { status: 200, body: RULES }));
  const { CodingEffectiveRules } = load("chat/coding/governance/CodingEffectiveRules.tsx", { fetch: srv.fetch, document: DOCUMENT() });
  const opened = [];
  const editable = [];
  let pipeline = 0;
  let workspaceCoding = 0;
  let view;
  await act(async () => { view = TestRenderer.create(createElement(CodingEffectiveRules, { workspaceId: "ws-1", workspaceName: "Northwind Claims",
    onOpenAdminTab: (tab) => opened.push(tab), onOpenPipeline: () => { pipeline += 1; },
    onOpenWorkspaceCoding: () => { workspaceCoding += 1; }, onEditableChange: (value) => editable.push(value) })); });
  const table = byTestId(view, "coding-rules-table")[0];
  assert.deepEqual(table.findAll((node) => node.type === "th").map(text), ["What", "Rule", "Applies to", "Source"]);
  const rows = table.findAll((node) => node.type === "tr").slice(1).map(text);
  assert.equal(rows.length, 5);
  assert.match(rows[0], /^Path blockedProduction manifests are reviewed by humansChanging filesPolicy v12$/);
  assert.match(rows[1], /^Path blockedAny \.env fileChanging files/);
  assert.match(text(view.root), /Four eyes/);
  assert.equal(editable.at(-1), false, "a person who may not change the rules gets no Add rule");
  assert.equal(view.root.findAll((node) => node.type === "input" || node.type === "select").length, 0, "nothing is editable here");
  // Every row opens its rule in the side panel; without the right to change it the panel is read only
  // and names its source and the place it is changed.
  for (let index = 0; index < 5; index += 1) {
    await act(async () => { bodyRows(view)[index].props.onClick(); });
    const panel = byTestId(view, "coding-rule-panel")[0];
    assert.ok(panel, `row ${index} opens the panel`);
    assert.equal(byTestId(view, "coding-rule-save").length, 0, "read only");
    assert.match(text(byTestId(view, "coding-rule-facts")[0]), /Source/);
    await act(async () => { byTestId(view, "coding-rule-edit-place")[0].props.onClick(); });
    assert.equal(byTestId(view, "coding-rule-panel").length, 0, "going to the rule's home closes the panel");
  }
  assert.deepEqual(opened, ["cedarPolicies", "policies", "approvalRule"]);
  assert.equal(workspaceCoding, 1);
  assert.equal(pipeline, 1);
  act(() => view.unmount());
});

test("rendered Coding rules: who may change the rules adds one in the side panel; it is saved with the Workspace's rules", async () => {
  const coding = { requires_governed_routing: false, tool_rules: [{ id: "no-env", kind: "path_denied", tools: ["Edit"], glob: "**/.env" }],
    client_deny: ["Read(./.env)"] };
  const srv = server((url, method, body) => (url.endsWith("/admin/workspaces/ws-1/coding")
    ? { status: 200, body: method === "PUT" ? body : coding } : { status: 200, body: RULES }));
  const { CodingEffectiveRules } = load("chat/coding/governance/CodingEffectiveRules.tsx", { fetch: srv.fetch, document: DOCUMENT() });
  const editable = [];
  let adding = false;
  let view;
  const props = () => ({ workspaceId: "ws-1", workspaceName: "Northwind Claims", onOpenAdminTab: () => {},
    onOpenPipeline: () => {}, adding, onAddingChange: (value) => { adding = value; }, onEditableChange: (value) => editable.push(value) });
  await act(async () => { view = TestRenderer.create(createElement(CodingEffectiveRules, props())); });
  assert.equal(editable.at(-1), true, "the page offers Add rule");
  adding = true;
  await act(async () => { view.update(createElement(CodingEffectiveRules, props())); });
  assert.equal(byTestId(view, "coding-rule-problems").length, 0, "no problem shown before anything is typed");
  await act(async () => { byTestId(view, "coding-rule-add")[0].props.onClick(); });
  assert.match(text(byTestId(view, "coding-rule-problems")[0]), /Enter the command/, "a save try names what is missing");
  assert.equal(srv.calls.filter((call) => call.method === "PUT").length, 0);
  const field = byTestId(view, "coding-rule-command")[0];
  await act(async () => { field.props.onChange({ target: { value: "git push origin release" } }); });
  await act(async () => { byTestId(view, "coding-rule-add")[0].props.onClick(); });
  const put = srv.calls.find((call) => call.method === "PUT");
  assert.ok(put.url.endsWith("/api/v1/admin/workspaces/ws-1/coding"));
  assert.deepEqual(put.body.tool_rules.map((rule) => rule.id), ["no-env", "command-git-push-origin-release"]);
  assert.deepEqual(put.body.client_deny, ["Read(./.env)"], "the Workspace's other settings stay as they are");
  assert.equal(adding, false);
  assert.match(text(view.root), /Rule added/);
  act(() => view.unmount());
});

test("rendered Coding rules: a Workspace rule is changed in its panel and removed with ⋯; built-in rules stay read only", async () => {
  const denied = [
    TOOL("no-push-to-main", "command_prefix_denied", { command: "git push origin main" }),
    TOOL("no-env", "path_denied", { glob: "**/.env", tools: ["Edit"] }, "workspace"),
    TOOL("no-rm", "command_prefix_denied", { command: "rm -rf /" }, "workspace"),
  ];
  let stored = [{ id: "no-env", kind: "path_denied", tools: ["Edit"], glob: "**/.env" }, { id: "no-rm", kind: "command_prefix_denied", prefix: ["rm", "-rf", "/"] }];
  const srv = server((url, method, body) => {
    if (url.endsWith("/admin/workspaces/ws-1/coding")) {
      if (method === "PUT") stored = body.tool_rules;
      return { status: 200, body: { requires_governed_routing: false, tool_rules: stored, client_deny: [] } };
    }
    return { status: 200, body: { ...RULES, denied } };
  });
  const { CodingEffectiveRules } = load("chat/coding/governance/CodingEffectiveRules.tsx", { fetch: srv.fetch, document: DOCUMENT(),
    window: { innerWidth: 1440, addEventListener() {}, removeEventListener() {} } });
  let view;
  await act(async () => { view = TestRenderer.create(createElement(CodingEffectiveRules, { workspaceId: "ws-1", workspaceName: "N",
    onOpenAdminTab: () => {}, onOpenPipeline: () => {} })); });
  const menus = () => view.root.findAll((node) => node.props["aria-label"]?.startsWith?.("More actions for") && node.type === "button");
  assert.deepEqual(menus().map((node) => node.props["aria-label"]), ["More actions for Any .env file", "More actions for rm -rf /"],
    "only the Workspace's own rules have ⋯");

  // The built-in rule: read only, with its source.
  await act(async () => { bodyRows(view)[0].props.onClick(); });
  assert.match(text(byTestId(view, "coding-rule-facts")[0]), /Built in: applies to every Workspace/);
  assert.equal(byTestId(view, "coding-rule-save").length, 0);

  // A Workspace rule: changed in its panel, saved with the same id and its file tools.
  await act(async () => { bodyRows(view)[1].props.onClick(); });
  assert.equal(byTestId(view, "coding-rule-glob")[0].props.value, "**/.env");
  await act(async () => { byTestId(view, "coding-rule-glob")[0].props.onChange({ target: { value: "**/.env*" } }); });
  await act(async () => { byTestId(view, "coding-rule-save")[0].props.onClick(); });
  const put = srv.calls.filter((call) => call.method === "PUT").at(-1);
  assert.deepEqual(put.body.tool_rules[0], { id: "no-env", kind: "path_denied", tools: ["Edit"], glob: "**/.env*" });
  assert.equal(byTestId(view, "coding-rule-panel").length, 0, "saved: the panel closes");
  assert.match(text(view.root), /Rule saved/);

  // Remove from the row's ⋯, after a confirmation.
  await act(async () => { menus()[1].props.onClick({ currentTarget: { getBoundingClientRect: () => ({ bottom: 0, right: 0 }) } }); });
  await act(async () => { view.root.findAll((node) => node.props.role === "menuitem" && text(node) === "Remove rule")[0].props.onClick(); });
  const confirm = view.root.findAll((node) => node.props.role === "alertdialog")[0];
  assert.ok(confirm, "a confirmation first");
  await act(async () => { confirm.findAll((node) => node.type === "button" && text(node) === "Remove rule")[0].props.onClick(); });
  assert.deepEqual(srv.calls.filter((call) => call.method === "PUT").at(-1).body.tool_rules.map((rule) => rule.id), ["no-env"]);
  assert.match(text(view.root), /Rule removed/);
  act(() => view.unmount());
});

test("rendered Delivery pipeline: stages and checks; adding a check saves it on the pipeline", async () => {
  const config = { id: "p1", name: "Workspace default", description: "", project_id: "ws-1", scope: {}, required_stage_keys: [],
    stages: [{ key: "plan", label: "Plan approved", required: true }, { key: "pr", label: "PR", required: true }],
    controls: {}, checks: [], review_status: "reviewed", is_active: true };
  const srv = server((url, method) => ({ status: 200, body: method === "PUT" ? config : { items: [config] } }));
  const { CodingDeliveryPipeline } = load("chat/coding/governance/CodingDeliveryPipeline.tsx", { fetch: srv.fetch });
  let view;
  await act(async () => { view = TestRenderer.create(createElement(CodingDeliveryPipeline, { workspaceId: "ws-1" })); });
  assert.match(text(byTestId(view, "delivery-pipeline")[0]), /Plan approved→PR/);
  await act(async () => { button(view, "+ Add check").props.onClick(); });
  const form = byTestId(view, "add-check")[0];
  await act(async () => { form.findAll((node) => node.type === "input")[0].props.onChange({ target: { value: "600" } }); });
  await act(async () => { button(view, "Add check").props.onClick(); });
  const saved = srv.calls.find((call) => call.method === "PUT");
  assert.deepEqual(saved.body.checks, [{ type: "pr_size_threshold", effect: "review", rule: { max_changed_lines: 600 } }]);
  act(() => view.unmount());
});
