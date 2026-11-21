// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/connectorCardGroups.test.mjs
//
// Connector UX (delivery 5): a connector card groups its fields under Connection, Authentication, Scope
// (and Settings), labels fields in words without the connector prefix, and shows no raw JSON example in the main
// view (stored values stay editable as JSON under "Advanced" or with a plain hint).
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { fieldGroup, fieldLabel, groupedFields } from "../../src/admin/components/connectorsTab/connectorFieldGroupsModel.ts";
import { hintStrings } from "./hintStrings.mjs";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");

test("fields are grouped by their role, in card order", () => {
  assert.deepEqual(groupedFields([
    "bitbucket_allowed_repos", "bitbucket_password", "bitbucket_url", "bitbucket_username", "knowledge_import_enabled",
  ], ["bitbucket_password"]), [
    { group: "connection", fields: ["bitbucket_url"] },
    { group: "authentication", fields: ["bitbucket_password", "bitbucket_username"] },
    { group: "scope", fields: ["bitbucket_allowed_repos"] },
    { group: "settings", fields: ["knowledge_import_enabled"] },
  ]);
  assert.equal(fieldGroup("confluence_oidc_client_id"), "authentication");
  assert.equal(fieldGroup("gcp_service_account_json", ["gcp_service_account_json"]), "authentication",
    "a secret is always Authentication, whatever its name");
  assert.equal(fieldGroup("confluence_allowed_pages"), "scope");
  assert.equal(fieldGroup("request_timeout_seconds"), "settings");
  assert.equal(fieldLabel("confluence", "confluence_allowed_spaces"), "Allowed spaces");
  assert.equal(fieldLabel("jenkins", "jenkins_url"), "URL");
  assert.equal(fieldLabel("aws", "aws_role_arn"), "Role ARN");
  assert.equal(fieldLabel("kubernetes", "k8s_api_url"), "K8s API URL");
});

function load(relative) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, JSON, encodeURIComponent,
      require: (name) => {
        if (name.endsWith(".css")) return {};
        if (name.startsWith(".")) {
          const base = path.resolve(path.dirname(file), name);
          for (const ext of [".tsx", ".ts"]) if (fs.existsSync(base + ext)) return loadFile(base + ext);
        }
        return require(name);
      },
    });
    return module.exports;
  };
  return loadFile(path.join(SRC, relative));
}

const groupsOf = (view) => view.root.findAll((node) => node.type === "fieldset").map((node) => node.props["data-group"]);
const textOf = (node) => (typeof node === "string" ? node : (node.children || []).map(textOf).join(""));
const REBIND = { flow: null, fieldEdited: () => {} };

test("rendered: the Confluence card shows Connection, Authentication and Scope in that order", () => {
  const { ConfluenceConnectorSetupFields } = load("admin/components/connectorsTab/ConfluenceConnectorSetupFields.tsx");
  const { atlassianAuthView } = load("admin/components/connectorsTab/atlassianAuthView.ts");
  const connector = {
    tool_name: "confluence", configured: true, secret_fields: ["confluence_token"], secret_status: {},
    fields: ["confluence_url", "confluence_auth_mode", "confluence_token", "confluence_allowed_spaces", "confluence_allowed_pages"],
    public_fields: { confluence_url: "https://wiki.example.test/wiki", confluence_auth_mode: "bearer_pat" },
  };
  const draft = { confluence_url: "https://wiki.example.test/wiki", confluence_auth_mode: "bearer_pat" };
  let view;
  act(() => {
    view = TestRenderer.create(createElement(ConfluenceConnectorSetupFields, {
      connector, draft, view: atlassianAuthView("confluence", connector, draft), ctx: { setConnectorField: () => {} },
      rebind: REBIND, showAllErrors: false,
    }));
  });
  assert.deepEqual(groupsOf(view), ["connection", "authentication", "scope"]);
  const [connection, authentication] = view.root.findAll((node) => node.type === "fieldset");
  assert.match(textOf(connection), /Confluence URL/);
  assert.doesNotMatch(textOf(connection), /Where Confluence runs/, "the sign-in is under Authentication");
  assert.match(textOf(authentication), /Where Confluence runs/);
  assert.doesNotMatch(textOf(authentication), /Confluence URL/);
});

test("rendered: the generic panel groups other connectors' fields and shows no JSON example", () => {
  const { ConfiguredConnectorFieldsPanel } = load("admin/components/connectorsTab/ConfiguredConnectorFieldsPanel.tsx");
  const connector = { tool_name: "bitbucket", fields: ["bitbucket_url", "bitbucket_password", "bitbucket_allowed_repos"],
    secret_fields: ["bitbucket_password"], secret_status: { bitbucket_password: true } };
  let view;
  act(() => {
    view = TestRenderer.create(createElement(ConfiguredConnectorFieldsPanel, {
      connector, draft: {}, ctx: { setConnectorField: () => {} }, rebind: REBIND,
    }));
  });
  assert.deepEqual(groupsOf(view), ["connection", "authentication", "scope"]);
  const all = textOf(view.root);
  assert.match(all, /ScopeAllowed reposA list, stored as JSON\./);
  const placeholders = view.root.findAll((node) => typeof node.props.placeholder === "string").map((node) => node.props.placeholder);
  assert.deepEqual(placeholders.filter((value) => /[[{]/.test(value)), [], "no JSON example as a placeholder");
  assert.ok(placeholders.includes("••••••• (stored — leave blank to keep)"));
});

test("no connector, named-connection or Workspace connector form holds a JSON example in a placeholder or hint", () => {
  const dirs = ["admin/components/connectorsTab", "admin/components/namedConnections", "admin/components/keyTags",
    "admin/components/connectorTest"];
  const files = [...dirs.flatMap((dir) => fs.readdirSync(path.join(SRC, dir)).map((name) => path.join(SRC, dir, name))),
    path.join(SRC, "admin/components/projectsTab/ProjectConnectorSettingsSection.tsx"),
    path.join(SRC, "admin/components/projectsTab/ProjectConnectorAccessPanel.tsx")]
    .filter((file) => /\.tsx?$/.test(file));
  const offenders = files.flatMap((file) => hintStrings(fs.readFileSync(file, "utf8"))
    .filter(({ text }) => /\[\s*\{|\{\s*"/.test(text))
    .map(({ text, line }) => `${path.relative(SRC, file)}:${line} ${text}`));
  assert.deepEqual(offenders, []);
});
