// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/jiraConnectorSetup.test.mjs
//
// Guided Jira connector setup (sign-in updated to the frozen contract): an explicit
// `jira_auth_mode` (Atlassian Cloud, or an own instance with username/password or a personal access
// token) chosen before the first save, an explicit project scope that never
// broadens silently, inline actionable errors, the existing secret-rebind flow, and an unchanged save
// body for every other connector.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import {
  jiraSaveFields,
  jiraSetupView,
  jiraUrlProblem,
  parseJiraProjects,
  projectsDisplayText,
} from "../../src/admin/components/connectorsTab/jiraConnectorSetupModel.ts";
import { storedAuthSummary } from "../../src/admin/components/connectorsTab/atlassianAuthModel.ts";
import { buildConnectorSaveBody } from "../../src/admin/hooks/connectorSaveBody.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.requestAnimationFrame = (callback) => callback();

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));

function makeLoader(stubs) {
  const cache = new Map();
  const resolve = (name, dir) => {
    if (name.endsWith(".css")) return {};
    const stub = Object.entries(stubs).find(([suffix]) => name.endsWith(suffix));
    if (stub) return stub[1];
    if (name.startsWith(".")) {
      const base = path.resolve(dir, name);
      for (const ext of [".tsx", ".ts"]) if (fs.existsSync(base + ext)) return load(base + ext);
    }
    return require(name);
  };
  const load = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, URL, URLSearchParams, console, requestAnimationFrame: globalThis.requestAnimationFrame,
      document: { getElementById: () => null }, require: (name) => resolve(name, path.dirname(file)),
    });
    return module.exports;
  };
  return (relative) => load(path.join(SRC, relative));
}

const Null = () => null;
const loadModule = makeLoader({
  "/ConfiguredConnectorHeader": { ConfiguredConnectorHeader: Null },
  "/ConfiguredConnectorHealthTools": { ConfiguredConnectorHealthTools: Null },
  "/ConfiguredConnectorToolList": { ConfiguredConnectorToolList: Null },
  "/ConfiguredConnectorGithubPanel": { ConfiguredConnectorGithubPanel: Null },
});

const JIRA_FIELDS = ["jira_url", "jira_auth_mode", "jira_email", "jira_token", "jira_username", "jira_password", "jira_allowed_projects"];
const POLICY = { tool_instructions: "keep", extra_tools: ["x"], disabled_tools: [] };

function jira({ publicFields = {}, secrets = {}, configured = true } = {}) {
  return {
    tool_name: "jira", label: "Jira", description: "Jira", fields: JIRA_FIELDS, secret_fields: ["jira_token", "jira_password"],
    supports_test: true, builtin_tools: [], tools: [], tool_policy: POLICY, is_active: true, policy_active: true, configured,
    public_fields: { jira_url: "https://acme.atlassian.net", ...publicFields },
    secret_status: { jira_token: false, jira_password: false, ...secrets }, db_id: null, policy_id: null,
  };
}

// The draft as the card opens it: every public field as a string, lists as pretty JSON.
function openedDraft(connector) {
  const draft = {};
  for (const [key, value] of Object.entries(connector.public_fields)) {
    draft[key] = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  }
  return draft;
}

const CLOUD = () => jira({ publicFields: { jira_auth_mode: "cloud_api_token", jira_email: "bot@acme.test" }, secrets: { jira_token: true } });
const UNSET = () => jira({ publicFields: { jira_email: "bot@acme.test" }, secrets: { jira_token: true } });
const summary = (connector) => storedAuthSummary("jira", connector);

// ---- model -----------------------------------------------------------------------------------

test("the saved sign-in method is read, never guessed from the stored fields, and never shown as verified", () => {
  const cases = [
    [jira({ configured: false, publicFields: { jira_url: "" } }), "none", null, "No sign-in method is saved yet."],
    [CLOUD(), "cloud_api_token", "cloud_api_token", /^Saved: Atlassian Cloud\.$/],
    [jira({ publicFields: { jira_auth_mode: "basic", jira_username: "svc" } }), "basic", "basic", /Own instance · Username and password, incomplete \(missing password\)/],
    [jira({ publicFields: { jira_auth_mode: "bearer_pat" }, secrets: { jira_token: true } }), "bearer_pat", "bearer_pat", /Own instance · Personal access token\.$/],
    [UNSET(), "none", null, "No sign-in method is saved yet."],
    [jira({ publicFields: { jira_auth_mode: "oauth" } }), "unknown", null, "The saved sign-in method is not recognised."],
  ];
  for (const [connector, stored, mode, text] of cases) {
    const view = jiraSetupView(connector, openedDraft(connector));
    assert.equal(view.auth.stored, stored);
    assert.equal(view.auth.mode, mode);
    if (text instanceof RegExp) assert.match(summary(connector), text);
    else assert.equal(summary(connector), text);
    assert.doesNotMatch(summary(connector), /verified|connected/i);
  }
  const unknown = jira({ publicFields: { jira_auth_mode: "oauth" } });
  const view = jiraSetupView(unknown, openedDraft(unknown));
  assert.match(view.errors.jira_auth_mode.message, /not recognised\. Choose one before saving/);
  assert.equal(view.errors.jira_auth_mode.live, true);
});

test("a setup without a saved method needs one before saving; an unchanged explicit one keeps its method", () => {
  const unset = UNSET();
  const unsetView = jiraSetupView(unset, openedDraft(unset));
  assert.equal(unsetView.auth.stored, "none");
  assert.equal(unsetView.scope, "all", "a configured setup without a list stays visibly unrestricted");
  assert.deepEqual(unsetView.errors, { jira_auth_mode: { message: "Choose how Jira signs in.", live: false } });

  const cloud = CLOUD();
  assert.deepEqual(jiraSetupView(cloud, openedDraft(cloud)).errors, {});
  assert.deepEqual(jiraSaveFields(cloud, openedDraft(cloud)), {
    jira_url: "https://acme.atlassian.net", jira_auth_mode: "cloud_api_token", jira_email: "bot@acme.test",
  });
});

test("switching Cloud to an own instance needs a fresh password and sends only the new method", () => {
  const connector = CLOUD();
  const draft = { ...openedDraft(connector), jira_auth_mode: "basic", __jira_auth_location: "own", jira_username: "svc-jira" };
  let view = jiraSetupView(connector, draft);
  assert.equal(view.auth.switching, true);
  assert.match(view.errors.jira_password.message, /Enter a new password: the sign-in method changes/);
  draft.jira_password = "pw-new";
  view = jiraSetupView(connector, draft);
  assert.deepEqual(view.errors, {});
  assert.deepEqual(jiraSaveFields(connector, draft), {
    jira_url: "https://acme.atlassian.net", jira_auth_mode: "basic", jira_username: "svc-jira", jira_password: "pw-new",
  });
});

test("project scope: restricted needs valid keys, normalizes and reports invalid entries without dropping them", () => {
  assert.deepEqual(parseJiraProjects("ops, river\nOPS ; 1bad\nok_2 te-st"), { keys: ["OPS", "RIVER", "OK_2"], invalid: ["1bad", "te-st"] });
  assert.deepEqual(parseJiraProjects('[\n  "OPS",\n  "river"\n]'), { keys: ["OPS", "RIVER"], invalid: [] });
  assert.equal(projectsDisplayText('[\n  "OPS",\n  "RIVER"\n]'), "OPS\nRIVER");

  const fresh = jira({ configured: false, publicFields: { jira_email: "bot@acme.test" } });
  const draft = { ...openedDraft(fresh), jira_token: "tok" };
  let view = jiraSetupView(fresh, draft);
  assert.equal(view.scope, "restricted", "a new setup starts restricted");
  assert.match(view.errors.jira_allowed_projects.message, /Add at least one project key, or choose all projects/);
  assert.equal("jira_allowed_projects" in jiraSaveFields(fresh, draft), false, "never [] and never an empty restriction");

  draft.jira_allowed_projects = "ops\n1bad";
  view = jiraSetupView(fresh, draft);
  assert.match(view.errors.jira_allowed_projects.message, /Not valid Jira project keys: 1bad/);
  assert.equal("jira_allowed_projects" in jiraSaveFields(fresh, draft), false);
  draft.jira_allowed_projects = "ops\nriver\nops";
  assert.deepEqual(jiraSaveFields(fresh, draft).jira_allowed_projects, ["OPS", "RIVER"]);
});

test("broadening a stored restriction needs the explicit confirmation and then clears with an empty value", () => {
  const connector = jira({
    publicFields: { jira_auth_mode: "cloud_api_token", jira_email: "bot@acme.test", jira_allowed_projects: ["OPS"] }, secrets: { jira_token: true },
  });
  const draft = { ...openedDraft(connector) };
  assert.equal(jiraSetupView(connector, draft).scope, "restricted");
  draft.__jira_scope = "all";
  const view = jiraSetupView(connector, draft);
  assert.equal(view.broadening, true);
  assert.match(view.errors.__jira_confirm_all_projects.message, /every project this account can access/);
  assert.equal("jira_allowed_projects" in jiraSaveFields(connector, draft), false);
  draft.__jira_confirm_all_projects = "true";
  assert.deepEqual(jiraSetupView(connector, draft).errors, {});
  assert.equal(jiraSaveFields(connector, draft).jira_allowed_projects, "");
});

test("URL: malformed and embedded credentials are refused; http stays allowed with a secure-use note", () => {
  assert.match(jiraUrlProblem("jira.example.com"), /Enter a full URL/);
  assert.match(jiraUrlProblem("https://bot:pw@jira.example.com"), /Remove the user name or password/);
  assert.match(jiraUrlProblem("ftp://jira.example.com"), /must start with https/);
  assert.match(jiraUrlProblem("https://jira.example.com/jira?x=1"), /query string/);
  assert.equal(jiraUrlProblem("https://jira.example.com/jira"), null);
  const connector = jira({ publicFields: { jira_url: "http://jira.internal/jira", jira_username: "svc" }, secrets: { jira_password: true } });
  const view = jiraSetupView(connector, openedDraft(connector));
  assert.equal(view.errors.jira_url, undefined);
  assert.match(view.urlNote, /http sends the credentials unencrypted/);
});

test("the save builder keeps the policy for Jira and leaves every other connector's body unchanged", () => {
  const connector = CLOUD();
  const body = buildConnectorSaveBody(connector, openedDraft(connector), POLICY);
  assert.deepEqual(body, {
    is_active: true, jira_url: "https://acme.atlassian.net", jira_auth_mode: "cloud_api_token", jira_email: "bot@acme.test",
    tool_policy: POLICY, policy_active: true,
  });
  const confluence = {
    ...connector, tool_name: "confluence", fields: ["confluence_url", "confluence_password", "confluence_allowed_spaces"],
    secret_fields: ["confluence_password"],
  };
  const other = buildConnectorSaveBody(
    confluence, { confluence_url: "https://wiki.example.test", confluence_password: "", confluence_allowed_spaces: '["A"]' }, POLICY,
  );
  assert.deepEqual(other, {
    is_active: true, confluence_url: "https://wiki.example.test", confluence_allowed_spaces: ["A"], tool_policy: POLICY, policy_active: true,
  });
});

// ---- rendered card ---------------------------------------------------------------------------

function mountCard(connector, { saveOutcome = { state: "saved" } } = {}) {
  const { ConfiguredConnectorCard } = loadModule("admin/components/connectorsTab/ConfiguredConnectorCard.tsx");
  let draft = openedDraft(connector);
  const saves = [];
  const tests = [];
  let view;
  const ctx = {
    CONNECTOR_COLORS: {}, connectorHealthHistory: {}, connectorTestResult: {}, connectorSaving: null, connectorTesting: null,
    expandedConnector: connector.tool_name,
    getConnectorDraft: () => draft,
    setConnectorField: (_tool, field, value) => {
      draft = { ...draft, [field]: value };
      act(() => view.update(render()));
    },
    handleSaveConnector: async (toolName, saved, confirmedBody) => {
      saves.push({ toolName, body: confirmedBody || buildConnectorSaveBody(saved, draft, POLICY) });
      return typeof saveOutcome === "function" ? saveOutcome(saves.length) : saveOutcome;
    },
    handleTestConnector: async (toolName) => tests.push(toolName),
  };
  const render = () => createElement(ConfiguredConnectorCard, { connector, ctx });
  act(() => { view = TestRenderer.create(render()); });
  const byId = (field) => view.root.find((node) => node.type !== undefined && node.props?.id === `connector-field-${connector.tool_name}-${field}`);
  const radio = (name, value) => view.root.find((node) => node.type === "input" && node.props.type === "radio"
    && node.props.name === `connector-field-${connector.tool_name}-${name}` && node.props.value === value);
  const button = (label) => view.root.find((node) => node.type === "button" && text(node) === label);
  const type = (field, value) => act(() => byId(field).props.onChange({ target: { value } }));
  const choose = (name, value) => act(() => radio(name, value).props.onChange());
  const click = async (label) => { await act(async () => { button(label).props.onClick(); }); };
  return { view: () => view, draft: () => draft, saves, tests, byId, radio, type, choose, click };
}

test("rendered: a stored Cloud setup shows only its pair, keeps the stored token and saves unchanged", async () => {
  const card = mountCard(CLOUD());
  const root = card.view().root;
  assert.equal(card.radio("jira_auth_mode", "cloud").props.checked, true);
  assert.equal(card.byId("jira_token").props.placeholder, "••••••• (stored — leave blank to keep)");
  assert.equal(root.findAll((node) => node.props?.id === "connector-field-jira-jira_username").length, 0, "no Server field");
  assert.equal(card.radio("__jira_scope", "all").props.checked, true);
  assert.match(text(root), /Currently saved: no project restriction/);
  assert.match(text(root), /Saved: Atlassian Cloud\./);
  await card.click("Save");
  assert.deepEqual(card.saves[0].body, {
    is_active: true, jira_url: "https://acme.atlassian.net", jira_auth_mode: "cloud_api_token", jira_email: "bot@acme.test",
    tool_policy: POLICY, policy_active: true,
  });
});

test("rendered: switching to an own instance asks for the method, explains the change and blocks a save without the new password", async () => {
  const card = mountCard(CLOUD());
  card.choose("jira_auth_mode", "own");
  await card.click("Save");
  assert.equal(card.saves.length, 0);
  assert.match(text(card.view().root), /Choose how your own instance signs in\./);
  card.choose("__jira_auth_location", "basic");
  assert.match(text(card.view().root), /The sign-in method changes: enter a new password/);
  card.type("jira_username", "svc-jira");
  await card.click("Save");
  assert.equal(card.saves.length, 0, "nothing is sent while the draft has errors");
  const root = text(card.view().root);
  assert.match(root, /Not saved: fix the highlighted fields\./);
  assert.match(root, /Enter a new password: the sign-in method changes/);
  assert.equal(card.byId("jira_password").props["aria-invalid"], true);
  card.type("jira_password", "pw-new");
  await card.click("Save");
  assert.equal(card.saves.length, 1);
  assert.equal(card.saves[0].body.jira_auth_mode, "basic");
  assert.equal("clear_secret_fields" in card.saves[0].body, false, "an explicit method never needs the pair replacement");
  assert.equal("jira_email" in card.saves[0].body, false, "the other method's fields are not sent");
});

test("rendered: a new setup starts restricted; invalid keys stay in the field with an inline error", async () => {
  const card = mountCard(jira({ configured: false, publicFields: { jira_url: "" } }));
  assert.equal(card.radio("__jira_scope", "restricted").props.checked, true);
  card.choose("jira_auth_mode", "cloud");
  card.type("jira_url", "https://acme.atlassian.net");
  card.type("jira_email", "bot@acme.test");
  card.type("jira_token", "tok");
  card.type("jira_allowed_projects", "ops\n1bad\nops");
  const root = text(card.view().root);
  assert.match(root, /Not valid Jira project keys: 1bad/, "an invalid entry is reported before any save");
  assert.doesNotMatch(root, /Saved as|Will save as/, "no normalized preview while an invalid entry remains");
  assert.equal(card.byId("jira_allowed_projects").props.value, "ops\n1bad\nops", "nothing typed is discarded");
  await card.click("Save");
  assert.equal(card.saves.length, 0);
  const refused = text(card.view().root);
  assert.match(refused, /Not saved: fix the highlighted fields\./);
  assert.doesNotMatch(refused, /Saved as|Will save as/);
  card.type("jira_allowed_projects", "ops\nRIVER\nops");
  const valid = text(card.view().root);
  assert.match(valid, /Will save as: OPS, RIVER/, "the unsaved draft is labelled as a preview");
  assert.doesNotMatch(valid, /Saved as:/);
  assert.match(valid, /Nothing saved yet\./);
  await card.click("Save");
  assert.deepEqual(card.saves[0].body.jira_allowed_projects, ["OPS", "RIVER"]);
});

test("rendered: removing a stored restriction needs the visible confirmation", async () => {
  const card = mountCard(jira({
    publicFields: { jira_auth_mode: "cloud_api_token", jira_email: "bot@acme.test", jira_allowed_projects: ["OPS"] }, secrets: { jira_token: true },
  }));
  assert.equal(card.byId("jira_allowed_projects").props.value, "OPS", "the stored list shows one key per line");
  card.choose("__jira_scope", "all");
  assert.match(text(card.view().root), /Saving removes the restriction to OPS/);
  await card.click("Save");
  assert.equal(card.saves.length, 0);
  assert.match(text(card.view().root), /Confirm that every project this account can access becomes reachable/);
  const confirm = card.view().root.find((node) => node.type === "input" && node.props.type === "checkbox");
  act(() => confirm.props.onChange({ target: { checked: true } }));
  await card.click("Save");
  assert.equal(card.saves[0].body.jira_allowed_projects, "");
});

test("rendered: a URL change refused for the kept token goes through the existing rebind flow", async () => {
  const refusal = { toolName: "jira", changedTargetFields: ["jira_url"], keptFields: ["jira_token"] };
  const card = mountCard(CLOUD(), {
    saveOutcome: (count) => (count === 1 ? { state: "secret_rebind_required", refusal, body: { jira_url: "https://other.atlassian.net" } } : { state: "saved" }),
  });
  card.type("jira_url", "https://other.atlassian.net");
  await card.click("Save");
  const root = card.view().root;
  assert.match(card.byId("jira_token").props.className, /security-field--attention/);
  assert.match(text(root), /Stored secret kept from the previous target\./);
  assert.match(card.byId("jira_url").props.className, /security-field--attention/);
});

test("rendered: the test action is labelled as testing the saved connection, not the draft or project access", async () => {
  const card = mountCard(CLOUD());
  const root = text(card.view().root);
  assert.match(root, /Test saved connection/);
  // What the test checks is the button's tooltip and in the Connector settings help, not a note.
  const button = card.view().root.find((node) => node.props?.["data-testid"] === "connector-test");
  assert.equal(button.props.title, "Checks the saved URL and account only, not unsaved changes and not access to the listed projects.");
  await card.click("Test saved connection");
  assert.deepEqual(card.tests, ["jira"]);
});

test("rendered: other connectors keep the generic panel and test label", () => {
  // Confluence has the guided sign-in since; a non-Atlassian connector stays generic.
  const jenkins = {
    ...CLOUD(), tool_name: "jenkins", fields: ["jenkins_url"], secret_fields: [], public_fields: { jenkins_url: "https://ci" },
    secret_status: {},
  };
  const card = mountCard(jenkins);
  const root = text(card.view().root);
  assert.match(root, /ConnectionURL/, "the generic panel groups its fields; labels without the connector prefix");
  assert.match(root, /Test connection/);
  assert.doesNotMatch(root, /Project access|Where .* runs/);
});

// ---- layout (screenshot 114): option rows and separate notes ------------------------------

test("rendered: every radio and checkbox sits first in its own row beside a wrapping text, in full-width groups", async () => {
  const card = mountCard(jira({ configured: false, publicFields: { jira_url: "" } }));
  const root = card.view().root;
  const groups = root.findAll((node) => node.props?.role === "radiogroup");
  assert.equal(groups.length, 2);
  for (const group of groups) assert.match(group.props.className, /\bjira-setup__group\b/);
  const controls = root.findAll((node) => node.type === "input" && (node.props.type === "radio" || node.props.type === "checkbox"));
  assert.equal(controls.length, 4, "two credential pairs and two scopes");
  for (const label of root.findAll((node) => node.type === "label" && node.props.className === "jira-setup__option")) {
    const [control, textPart] = label.children;
    assert.equal(control.type, "input", "the control comes first in the row");
    assert.equal(textPart.props.className, "jira-setup__option-text");
  }
  assert.equal(root.findAll((node) => node.type === "label" && node.props.className === "jira-setup__option").length, 4);
  assert.equal(root.findAll((node) => /connector-field--checkbox/.test(node.props?.className || "")).length, 0,
    "options do not use the column field style");
});

test("the Jira stylesheet lays options out as a row with an intrinsic control and only styles its own classes", () => {
  const css = fs.readFileSync(new URL("../../src/admin/components/connectorsTab/jiraConnectorSetup.css", import.meta.url), "utf8");
  const rule = (selector) => {
    // The exact selector, alone or first in a selector list (".jira-setup__option" is not ".jira-setup__options").
    const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const match = css.match(new RegExp(`(?:^|[\\n,])\\s*${escaped}\\s*(?:,[^{]*)?\\{([^}]*)\\}`));
    assert.ok(match, `missing rule for ${selector}`);
    return match[1];
  };
  assert.match(rule(".jira-setup__option"), /display:\s*flex;[\s\S]*flex-direction:\s*row;[\s\S]*align-items:\s*flex-start;/);
  assert.match(rule('.jira-setup__option input[type="radio"]'), /flex:\s*0 0 auto;[\s\S]*width:\s*auto;/);
  assert.match(rule(".jira-setup__option-text"), /min-width:\s*0;[\s\S]*overflow-wrap:\s*anywhere;/);
  assert.match(rule(".jira-setup__group"), /grid-column:\s*1 \/ -1;/);
  const selectors = [...css.replace(/\/\*[\s\S]*?\*\//g, "").matchAll(/([^{}]+)\{/g)].flatMap((match) => match[1].split(","));
  for (const selector of selectors) assert.match(selector.trim(), /^\.jira-setup__/, `no global selector: ${selector.trim()}`);
  assert.doesNotMatch(css.replace(/\/\*[\s\S]*?\*\//g, ""), /#[0-9a-f]{3,6}\b|rgb\(/i, "existing theme tokens only");
});

test("rendered: the save error and the connection-test note are separate paragraphs", async () => {
  const card = mountCard(jira({ configured: false, publicFields: { jira_url: "" } }));
  await card.click("Save");
  const root = card.view().root;
  const notes = root.find((node) => node.props?.className === "jira-setup__notes");
  const paragraphs = notes.findAll((node) => node.type === "p");
  assert.deepEqual(paragraphs.map(text), ["Not saved: fix the highlighted fields."]);
  assert.equal(paragraphs[0].props.role, "alert");
});
