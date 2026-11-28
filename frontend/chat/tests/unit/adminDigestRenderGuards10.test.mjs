// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/adminDigestRenderGuards10.test.mjs
//
// Render guards for the designer inspector forms, the ServiceNow connector setup and the Teams delivery targets, whose
// long functions are split into smaller parts: each renders with representative props, keeps its key labels and keeps
// its whole rendered tree (a digest of the test renderer's JSON), so the split draws exactly what the original drew.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement as h } from "react";
import { act, byId, digest, loadModule, mount, noop, text } from "./adminDigestRenderHarness.mjs";

const json = (props) => JSON.stringify(props, (key, value) => (typeof value === "function" ? "fn" : key === "children" ? undefined : value));
const part = (name) => (props) => h("part", { name, data: json(props) }, props.children);

// --- Designer inspector: the form per box kind ----------------------------------------------------------------------

const CATALOG = {
  agents: [], tools: ["git_push", "jira_update"],
  checkTypes: [{ type: "tests_pass", label: "Tests pass", params: ["command"] }, { type: "lint", label: "Lint", params: [] }],
  gateCheckTypes: ["tests_pass", "lint", "custom_check"], workflows: [{ key: "wf-sub", title: "Sub flow" }],
  platformActions: [{ key: "open_pr", label: "Open a pull request", routes: ["succeeded", "failed"] }],
  confirmationSubjects: ["plan", "functional_acceptance"], watchConditions: ["pr_merged", "ci_green"],
  outcomes: ["done", "failed"], deciders: ["requester", "workspace_admin"],
  workItemFields: [{ key: "priority", label: "Priority", kind: "enum", values: ["high", "low"] },
    { key: "points", label: "Points", kind: "number" }, { key: "labels", label: "Labels", kind: "list" }],
};
const PHASE = { id: "build", type: "phase", label: "Build", config: { result_values: ["done", "blocked", "retry"] } };
const NODES = [{ id: "start", type: "start", label: "Start", config: {} }, PHASE,
  { id: "gate", type: "gate", label: "Gate", config: {} }, { id: "end", type: "outcome", label: "End", config: { outcome: "done" } }];
const formProps = (node, extra = {}) => ({
  node, nodes: [...NODES, node], edges: [], catalog: CATALOG, editable: true, issues: [], set: noop, setAll: noop, replace: noop,
  workflowKey: "bugfix", ...extra,
});
const BOXES = [
  { id: "g1", type: "gate", label: "", config: { checks: [{ type: "tests_pass", command: "npm test" }], phase: "build" } },
  { id: "a1", type: "approval", label: "", config: { decider: "workspace_admin", title: "Merge", summary: "Fix" } },
  { id: "a2", type: "approval", label: "", config: {} },
  { id: "u1", type: "user_confirmation", label: "", config: { subject: "plan", on_open_high: "" } },
  { id: "q1", type: "user_conversation", label: "", config: { question: "Which branch?" } },
  { id: "w1", type: "watch", label: "", config: { conditions: ["pr_merged", "gone"] } },
  { id: "p1", type: "platform_action", label: "", config: { action: "open_pr" } },
  { id: "p2", type: "platform_action", label: "", config: { tool: "git_push", arguments: { force: false } } },
  { id: "s1", type: "sub_workflow", label: "", config: { workflow_key: "wf-sub" } },
  { id: "o1", type: "outcome", label: "", config: { outcome: "failed" } },
  { id: "x1", type: "start", label: "" }, { id: "x2", type: "pause", label: "" }, { id: "x3", type: "review", label: "" },
  { id: "x4", type: "unknown_kind", label: "" },
];

test("inspector form: the fields of every box kind, editable and read-only", async () => {
  const path = "admin/components/agentsWorkflows/canvas/designer/inspector/NodeInspectorForm.tsx";
  const stubs = { "/PhaseForm": { PhaseForm: part("PhaseForm") }, "/DecisionForm": { DecisionForm: part("DecisionForm") },
    "/ParallelWorkForm": { ParallelWorkForm: part("ParallelWorkForm") } };
  const digests = [];
  for (const node of [...BOXES, PHASE, { id: "d1", type: "decision", label: "", config: {} }, { id: "pw", type: "parallel_work", label: "" }]) {
    for (const editable of [true, false]) {
      const view = await mount(path, "Form", formProps(node, { editable }), { stubs });
      digests.push(view.toJSON() === null ? "0" : digest(view));
    }
  }
  assert.equal(digests.filter((value) => value === "0").length, 2);
  assert.equal(digests.join(","), "1e337928781c5394f4c81365dad3b831259d42b899ae740f9b42dd35570033e1,369faeb2270386b8fb79e67ba9b15314ab64d30ebf5e628637c24252deeab64b,90b795b5d1782100245b93f41e7940986417eb4450e3e66e87346be3eb23c138,16270aeda0e0ed282b280185e76f1a2b9461c78a3a67acbe00fae49b6a677d48,5a99e8f75a21d76fae26ad3c58866791eedf762c712b67be70cd99fcc4c8f69c,8471937e79625f65e729150049267425179ace1ee8e4921f76538a970d1c6959,ffd33618362778a5762ea609601ded202ffe6a98e333a41adcebe08ac3a5a146,c163409abe2c3242712bda5cd73af827c5d55e2e13ecfb58f4f9a350e15c66dd,a444d79045da5a19a9c170dd08a9faf254ebeb0e8ac74be6e4eee725c2ddc0f2,ac9e2a8d5635f2bb906f58e8df4fe23df8b562915487d82d545255a3bbb5bf1a,b6f36b888ae039591ea6d3d9d3f5ed6f4a1baf5693f28d9b68d8773fdf84df21,ded7fe308b2cf822d71ac2fbea7369e1f1880a8bda7e8b710f91a4bb745a96d4,1ff7e6fe9b44a60ffe02364c9cacd87465b6a388f06e5c83f3daba2eab7a13d0,3e419ada55ea386bc211f65b9dfc30330677ed205d9535d46811e1c7c0340dae,435518dc65399b87cc6a7277949d970315df6f866cd686c38a36b1ad7e25c8d2,54c5f646e08cb7beadefff280f7d30db6acc3c611ba8a7bd7a81ab9efe307e52,d70ea8752d5810e0f39386c06d7168072b9319b8a377f9c100f0abfbe9a38892,7fe44bebdac2aa70b73b9fb26a2e1517e19dfdcc4960bdbc739c0ea49c069f79,c16c3e62f442e5e36eb35e1e7e3bc0bff4c64baf9927cec8bef647017a8e8635,1cf29b1fa5004ca2aeccb2fb4073ca38e9a445c8fee0c14cc785536f48269787,7ddeef97f2a09b647f16a46cfffa54cf326afe1c30167d7b093f54b041ddda7e,7ddeef97f2a09b647f16a46cfffa54cf326afe1c30167d7b093f54b041ddda7e,f5bf2c513d8b543d35460f6d235773b33b57542ff1dd0561e3ef5d2c0e48f0be,f5bf2c513d8b543d35460f6d235773b33b57542ff1dd0561e3ef5d2c0e48f0be,248960a35e15bc3aa06f051085ce026b888efe10f82dd15d2dcd0b83f9307713,248960a35e15bc3aa06f051085ce026b888efe10f82dd15d2dcd0b83f9307713,0,0,f13a4887418bc4b3ebd260cc07fdf362ee270ee1f5000d20e9523b3f2a4e5069,bec1c52f7fb3edd813f0719e9124c4320d8a249e1c4a78c1a9fe3669dfc83e11,07c04cd8601bdf6a9ab928f9a5844eaa67fa022b4061a966323677a8cb41d6ec,605075cbaeee3c85efdc067a6bc17efd0ebda0c7bdaf5a1ef7955b7b369aee76,75fc6f5ded89872f29122a70c78db4d94091a6958745ca92a74a4321d47716c4,f90f1b4d1d2404292fcc2cdaae49e96392153cd5a4ee1dde7d6e298aec44fc0a");
});

// --- Designer inspector: the condition form -------------------------------------------------------------------------

const DECISIONS = [
  ["field mode, enum", { check: "field", field: "priority", operator: "equals", value: "high" }, []],
  ["field mode, number", { check: "field", field: "points", operator: "gt", value: 3 }, [["yes", "end"]]],
  ["field mode, list", { check: "field", field: "labels", operator: "contains", value: "" }, [["yes", "end"], ["no", "gate"]]],
  ["field mode, no field", { check: "field", field: "", operator: "", value: "" }, []],
  ["result mode, routed and stale", { source: "build", options: ["done", "gone"] }, [["done", "end"], ["otherwise", "gate"]]],
  ["result mode, unrouted", { source: "build", options: ["done"] }, []],
  ["result mode, no source", { source: "", options: [] }, []],
];

test("condition form: field and result modes, routes, fallbacks, stale results; with and without arrows, read-only", async () => {
  const path = "admin/components/agentsWorkflows/canvas/designer/inspector/DecisionForm.tsx";
  const digests = [];
  for (const [, config, routes] of DECISIONS) {
    const node = { id: "d1", type: "decision", label: "Check", config };
    const edges = routes.map(([when, target], index) => ({ id: `e${index}`, source: "d1", target, kind: "next", when }));
    for (const extra of [{ onRoute: noop }, {}, { onRoute: noop, editable: false }, { catalog: { ...CATALOG, workItemFields: [] } }]) {
      const view = await mount(path, "DecisionForm", formProps(node, { edges, ...extra }));
      digests.push(digest(view));
    }
  }
  assert.equal(digests.join(","), "4a904333d65583e5c36ca2179629c1955c44d75e4f7752e1dc961244a5266648,4e779d5a673833cd2c17277304d6bbad15475be766da144fff49cbd0c29ae21e,2fd804a5620e14793f8948d3bb7aa3a7537bc5b4704fddba6ba117d7b2d20046,eed2ac346a840078a3f8783d359348b58ce980169f6351aeddb14ac6c90dd9de,c050f518d46142148546893e7c8ae11208089c9c32d6567369e0f98b47c00c1b,e84ba016e2a1103eff6c49c632692f534785837cb4d94b1b42e97a855a30dc21,00180c33e84ca34a453783fd8a30d4b29dfa18cefcb6f568d3563e719d9b3712,df5c652d1333a54b8b58bb295c3b4d86f77a23ba33bb9eab3f6554087892176b,e51ff31cad4775d90b1ced2ba89e39ad48946f15f3559914e841e9723e6ba6ef,c62ba867ef0acc9262988dcd08f4322121dba3e7f59a1f85f8cef3d02bbeb378,27eeeddf526e597ce42529051321eee12f42c604fa0ecef643f7c509563cb800,db7d9bd7f0ff25597bd83d7602cc37034791cf7f5f926cb418100b02b4f4be7a,dbaa83fb585a0f7d76711522cf0e17390bf47526ee603a7a320965614ca3ab54,1a4470814948decb8d93fd9e6ea4f8b331d4bc0e2886125a4aaf01380fc17f97,dbd69d940b42dbd729fccec53950464398e25d5fe475b401ac5bdb88e50a2558,6d2405ea6884d30a54c553c57877ec2e3a91ff3432c1a498ce2c11abddcc4bf0,cc2166f304167a6cc206d0f99e80a48d8ed47d27ef58bc49d031d75c3e13ed79,24c8d6d6567cff9cb9fe3ab08f51f658623eba22c2cc96af48635c6b6349342c,715cfdb489eaf03c2d43fd85b22de8dfd95405a1d62b0a2664c231c97e7e75d5,65aee698a724ce425e36d323eaa684bc0b631289827b78f2bc6eb50613612c27,58fc4a99d663733b317a1aea3fb55a3aed1658d360fc8193a8b35199385d7e9e,5b26663970a4e846b5ecbde76e8a683c8533be1f26cfb1c4eefc5e1f27b15bfd,2520044f19b4856d4620249dae94c26e20ae089477a3d271fd1d2d0d521bf638,26ceed554194e9c161c41d92671dfc9a5cbe83fe3c79af12dc15777791f598bd,32275f24acc75c27748d0a97852148fc79d7e6c7621cdccd18e39f7a88d9651a,32275f24acc75c27748d0a97852148fc79d7e6c7621cdccd18e39f7a88d9651a,3a9e6feb2af273d83424643e496b795fc4f9c5a70bfd76f6d4b5250a87615eff,79aff274fbd4710539192b2ec121049adc2fe06c5e5d3b599ba25864c15b0b22");
});

// --- ServiceNow connector setup -------------------------------------------------------------------------------------

const SN_CONNECTOR = (publicFields, secretStatus = {}) => ({
  tool_name: "servicenow", label: "ServiceNow", fields: ["servicenow_url", "servicenow_auth_mode", "servicenow_tables"],
  public_fields: publicFields, secret_status: secretStatus, tools: [],
});
const SN_CASES = [
  [SN_CONNECTOR({}), { servicenow_url: "" }, false],
  [SN_CONNECTOR({ servicenow_username: "bot" }, { servicenow_password: true }), { servicenow_url: "https://acme.service-now.com" }, true],
  [SN_CONNECTOR({ servicenow_auth_mode: "basic" }, { servicenow_password: true }),
    { servicenow_url: "https://acme.service-now.com", servicenow_auth_mode: "oauth_password" }, true],
  [SN_CONNECTOR({ servicenow_auth_mode: "oidc_client_credentials" }),
    { servicenow_url: "https://acme.service-now.com", servicenow_auth_mode: "oidc_client_credentials" }, false],
  [SN_CONNECTOR({ servicenow_auth_mode: "bearer_token" }, { servicenow_token: true }),
    { servicenow_url: "http://bad", servicenow_auth_mode: "bearer_token" }, true],
];

test("ServiceNow setup: URL, sign-in methods (none saved, switching, OIDC, password OAuth, token), scope and the rest", async () => {
  const path = "admin/components/connectorsTab/ServiceNowConnectorSetupFields.tsx";
  const { serviceNowSetupView } = loadModule("admin/components/connectorsTab/serviceNowApiModel.ts");
  const stubs = { "/ServiceNowAssignmentGroupsField": { ServiceNowAssignmentGroupsField: part("Groups") },
    "/ConfiguredConnectorFieldsPanel": { ConfiguredConnectorFieldsPanel: part("Rest") } };
  const digests = [];
  for (const [connector, draft, showAllErrors] of SN_CASES) {
    const view = await mount(path, "ServiceNowConnectorSetupFields", {
      connector, draft, view: serviceNowSetupView(connector, draft), ctx: { setConnectorField: noop },
      rebind: { flow: null, fieldEdited: noop }, showAllErrors,
    }, { stubs });
    assert.equal(byId(view.root, "servicenow-auth").length, 1);
    digests.push(digest(view));
  }
  assert.equal(digests.join(","), "5531007f0fe83b851fae6721136f0940dcc3e5bd0003ea80a22afe29e098f3ac,d7291addbe2f0289095183192bc3624965f9dc2f0a628360bc86e61e4bf3dff0,472de4956d027f417566f975c6a881c19eafb2e26b0c007713bdec7cbb5ac177,91744acdf71b581dd26c5fcdfb59029fffa292ed9e69323f6b109ed6ba470e0b,2c38ab3a6f76d8e62f1b0e943adb4b7f0abb4890c58a50d56461e6bf60df5b85");
});

// --- Teams delivery targets -----------------------------------------------------------------------------------------

const TARGET_PROPS = {
  channels: [{ id: 1, name: "Ops bot", plugin_id: "msteams" }, { id: 2, name: "Slack", plugin_id: "slack" }],
  projects: [{ id: "p-1", name: "Claims" }],
  targets: [{ id: "t-1", project_id: "p-1", event_type: "approval.requested", channel_config_id: 1, target: "19:abc", is_active: true },
    { id: "t-2", project_id: null, event_type: "custom.event", channel_config_id: null, target: "19:def", is_active: false },
    { id: "t-3", project_id: "p-9", event_type: "trace.alert.triggered", channel_config_id: 7, target: "19:ghi", is_active: true }],
  projectId: "p-1", setProjectId: noop, eventType: "approval.requested", setEventType: noop, channelId: "", setChannelId: noop,
  target: "19:new", setTarget: noop, loading: false, error: "Target refused", onCreate: async () => true, onDelete: noop,
  onSetUpChannel: noop,
};

test("Teams delivery targets: table, the add panel with its fields, empty and no-Teams states", async () => {
  const path = "admin/components/AdminChannelDeliveryTargetsPanel.tsx";
  const view = await mount(path, "AdminChannelDeliveryTargetsPanel", TARGET_PROPS);
  assert.match(text(view.root), /Teams delivery targets \(3\)/);
  const digests = [digest(view)];
  await act(async () => { byId(view.root, "delivery-target-add")[0].props.onClick(); });
  assert.equal(byId(view.root, "delivery-target-panel").length > 0, true);
  digests.push(digest(view));
  const busy = await mount(path, "AdminChannelDeliveryTargetsPanel", { ...TARGET_PROPS, targets: [], loading: true, error: null });
  digests.push(digest(busy));
  await act(async () => { busy.root.findAllByType("button").find((node) => text(node) === "Add delivery target").props.onClick(); });
  digests.push(digest(busy));
  const noTeams = await mount(path, "AdminChannelDeliveryTargetsPanel", { ...TARGET_PROPS, channels: [] });
  assert.equal(byId(noTeams.root, "delivery-targets-need-teams").length > 0, true);
  digests.push(digest(noTeams));
  assert.equal(digests.join(","), "281480fc8b96b39ca5f5a9843b5a1a4e830ebfc57e7cfcc94bb368feb86e0efa,e9cb7b6aa9941fe7ddc08e8a1aae86d596ce4ebf125d7fd29cbf60aef2547824,047e51d04f334e47c3ab8fc3a93d7e8a8a6278e0c733a05b06fea0443c8988cb,99b2e63102a1783042f7395f5373b43a0674d499bbc9f580057bda15dd8ca800,583c08becbbe6a7dbf29888b54edd627dbe1c80c0ef319eaeadc6fa7249ad992");
});
