// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/workspaceListLayout.test.mjs
//
// Admin › Workspaces in the new style (central configuration, UX review): one full-width table with Name,
// Class, Members, Problems and Updated; a row opens the Workspace page; Make default, Archive/Restore and Delete live
// in the row's ⋯ menu. Agent templates, Design readiness and "Open settings" are gone.
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { createRequire } from "node:module";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import * as listModel from "../../src/admin/components/projectsTab/workspaceListModel.ts";
import * as listRow from "../../src/admin/components/projectsTab/workspaceListRow.ts";
import * as dataTable from "../../src/layout/DataTable.ts";
import * as statusLabel from "../../src/layout/StatusLabel.ts";

const text = (node) => (node === null ? "" : typeof node === "string" ? node : node.children.map(text).join(""));
const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const workspaces = [
  { id: "p-1", name: "Petclinic", description: "Spring demo\n  with a long   description", is_active: true,
    class: "confidential", member_count: 4, updated_at: "2026-11-06T10:00:00+00:00" },
  { id: "p-2", name: "Archived test", description: "", is_active: false, template_key: "tpl" },
  { id: "p-0", name: "Default", description: "", is_active: true, is_system: true, is_default: true },
];

function loadSection() {
  const source = fs.readFileSync(new URL("../../src/admin/components/AdminProjectsSummarySection.tsx", import.meta.url), "utf8");
  const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  const exports = {};
  const ActionMenu = ({ row, items }) =>
    createElement("div", { "data-menu": `⋯ ${row.objectName}` },
      ...items.map((item) => createElement("button", { key: item.label, type: "button", "data-danger": item.danger ? "yes" : "no",
        disabled: item.disabled, onClick: item.onSelect }, item.label)));
  const TimeText = ({ value }) => createElement("time", null, value || "—");
  vm.runInNewContext(output, {
    exports,
    require: (name) => {
      if (name.endsWith(".css")) return {};
      if (name.endsWith("/ActionMenu")) return { ActionMenu };
      if (name.endsWith("/workspaceListModel")) return listModel;
      if (name.endsWith("/workspaceListRow")) return listRow;
      if (name.endsWith("/layout/DataTable")) return dataTable;
      if (name.endsWith("/layout/StatusLabel")) return statusLabel;
      if (name.endsWith("/utils/TimeText")) return { TimeText };
      return require(name);
    },
  });
  return exports.AdminProjectsSummarySection;
}

function render(props) {
  const Section = loadSection();
  let view;
  act(() => { view = TestRenderer.create(createElement(Section, { handleOpenProjectQualityForm: () => {}, ...props })); });
  return view;
}

const headers = (view) => view.root.findAllByType("th").map((th) => text(th)).filter(Boolean);
const bodyRows = (view) => view.root.findAllByType("tbody")[0].findAllByType("tr");

test("the row presenter reads name, badges, class, members and change time", () => {
  const row = listRow.workspaceListRow(workspaces[0]);
  assert.equal(row.description, "Spring demo with a long description");
  assert.equal(row.descriptionTitle, "Spring demo\n  with a long   description");
  assert.equal(row.classLabel, "Confidential");
  assert.equal(row.members, 4);
  assert.equal(row.updatedAt, "2026-11-06T10:00:00+00:00");
  assert.deepEqual(listRow.workspaceListRow(workspaces[2]).badges, ["default", "system"]);
  assert.deepEqual(listRow.workspaceListRow(workspaces[1]).badges, ["template"]);
  const plain = listRow.workspaceListRow(workspaces[1]);
  assert.equal(plain.classLabel, "—");
  assert.equal(plain.members, null);
  assert.equal(plain.updatedAt, null);
  assert.deepEqual(listRow.problemCountsByWorkspace([
    { severity: "problem", workspace: { id: "p-1" } },
    { severity: "attention", workspace: { id: "p-1" } },
    { severity: "attention", workspace: null },
  ]), { "p-1": { total: 2, problem: 1 } });
});

test("columns are Name, Class, Members, Problems and Updated; no templates, readiness or Open settings", () => {
  const view = render({ adminProjects: workspaces, problemCounts: { "p-1": { total: 2, problem: 1 } } });
  assert.deepEqual(headers(view), ["Name", "Class", "Members", "Problems", "Updated", "Actions"]);
  const all = text(view.root);
  for (const gone of ["Agent templates", "Design readiness", "Open settings", "Code repositories"]) {
    assert.equal(all.includes(gone), false, gone);
  }
  assert.equal(bodyRows(view).length, 2, "the active filter starts on active Workspaces");
  const first = bodyRows(view).find((tr) => text(tr).includes("Petclinic"));
  assert.match(text(first), /Confidential/);
  assert.match(text(first), /4/);
  assert.match(text(first), /2/);
  act(() => view.unmount());
});

test("Members, Updated and Problems are left out when the payload or the problems call does not carry them", () => {
  const view = render({ adminProjects: [workspaces[2]], problemCounts: null });
  assert.deepEqual(headers(view), ["Name", "Class", "Actions"]);
  act(() => view.unmount());
});

test("a row opens the Workspace page; the ⋯ menu keeps Make default, Archive and Delete", () => {
  const opened = [];
  const archived = [];
  const deleted = [];
  const view = render({
    adminProjects: workspaces,
    handleOpenProjectQualityForm: (project) => opened.push(project.id),
    onArchiveProject: (project) => archived.push(project.id),
    onDeleteProject: (project) => deleted.push(project.id),
  });
  const row = bodyRows(view).find((tr) => text(tr).includes("Petclinic"));
  act(() => row.props.onClick());
  assert.deepEqual(opened, ["p-1"]);
  const menu = view.root.find((node) => node.props["data-menu"] === "⋯ Petclinic");
  const items = menu.findAllByType("button");
  assert.deepEqual(items.map((item) => text(item)), ["Make default", "Archive…", "Delete…"]);
  assert.deepEqual(items.filter((item) => item.props["data-danger"] === "yes").map((item) => text(item)), ["Delete…"],
    "Archive is reversible, so it is not red");
  act(() => items[1].props.onClick());
  act(() => items[2].props.onClick());
  assert.deepEqual([archived, deleted], [["p-1"], ["p-1"]]);
  const systemMenu = view.root.find((node) => node.props["data-menu"] === "⋯ Default");
  assert.ok(systemMenu.findAllByType("button").slice(1).every((item) => item.props.disabled), "the default Workspace cannot be archived or deleted");
  act(() => view.unmount());
});

test("Create workspace is the one primary action; an empty list reads one line with it; the filter still works", () => {
  let asked = 0;
  const view = render({ adminProjects: workspaces, onCreateWorkspace: () => { asked += 1; } });
  const create = view.root.find((node) => node.props["data-testid"] === "workspace-create");
  act(() => create.props.onClick());
  assert.equal(asked, 1);
  act(() => view.root.findByType("select").props.onChange({ target: { value: "inactive" } }));
  assert.deepEqual(bodyRows(view).map((tr) => text(tr.findByType("strong"))), ["Archived test"]);
  act(() => view.unmount());
  const empty = render({ adminProjects: [], onCreateWorkspace: () => {} });
  const line = empty.root.find((node) => node.props["data-testid"] === "empty-line");
  assert.match(text(line), /^No workspaces yet\.Create workspace$/);
  act(() => empty.unmount());
});

// ---- UI check C7: the Class column showed "—" in every row ------------------------------------------

test("The class cell names the level, or says Not set with Set class, or offers Show class when unreadable", () => {
  const classes = listRow.readWorkspaceClasses({ workspaces: [
    { id: "p-0", name: "Default", level: "internal", source: "instance_default" },
    { id: "p-3", name: "New", level: null, source: "unset" },
    { bad: true },
  ] });
  assert.deepEqual(classes, { "p-0": { level: "internal", source: "instance_default" }, "p-3": { level: null, source: "unset" } });
  const row = (id, extra = {}) => ({ id, classLabel: "—", isActive: true, ...extra });
  assert.deepEqual(listRow.workspaceClassCell(row("p-0"), classes), { label: "Internal", title: "From the instance default", action: null });
  assert.deepEqual(listRow.workspaceClassCell(row("p-3"), classes).label, "Not set");
  assert.equal(listRow.workspaceClassCell(row("p-3"), classes).action, "set");
  assert.equal(listRow.workspaceClassCell(row("p-1", { classLabel: "Confidential" }), null).label, "Confidential");
  // The levels could not be read (not a platform admin): no claim, a way to look.
  assert.deepEqual(listRow.workspaceClassCell(row("p-9"), null), { label: "", title: "", action: "show" });
  // An archived Workspace is not in the active list: unknown, not "Not set".
  assert.equal(listRow.workspaceClassCell(row("p-2", { isActive: false }), classes).action, "show");
  for (const id of ["p-0", "p-3", "p-9"]) assert.notEqual(listRow.workspaceClassCell(row(id), classes).label, "—");
});

test("rendered: no dash in the Class column; Set class opens the Workspace's classification, not the row", () => {
  const opened = [];
  const classified = [];
  const view = render({
    adminProjects: workspaces,
    workspaceClasses: { "p-0": { level: null, source: "unset" } },
    handleOpenProjectQualityForm: (project) => opened.push(project.id),
    onOpenClassification: (project) => classified.push(project.id),
  });
  const defaultRow = bodyRows(view).find((tr) => text(tr).includes("Default"));
  const classCell = defaultRow.findAllByType("td")[1];
  assert.equal(text(classCell), "Not setSet class");
  const set = view.root.find((node) => node.props["data-testid"] === "workspace-class-set-p-0");
  let stopped = false;
  act(() => set.props.onClick({ stopPropagation: () => { stopped = true; } }));
  assert.deepEqual([classified, opened, stopped], [["p-0"], [], true]);
  assert.equal(text(bodyRows(view).find((tr) => text(tr).includes("Petclinic")).findAllByType("td")[1]), "Confidential");
  act(() => view.unmount());
});

test("Set class opens Rules with the classification card first", async () => {
  const link = await import("../../src/admin/components/projectsTab/workspaceSettingsLink.ts");
  link.requestWorkspaceSettings("p-0", "rules", "classification");
  assert.equal(link.takeWorkspaceSettingsRequest("p-1"), null, "another Workspace does not take it");
  assert.deepEqual(link.takeWorkspaceSettingsRequest("p-0"), { section: "rules", focus: "classification" });
  assert.equal(link.takeWorkspaceSettingsSection("p-0"), null, "taken once");
  link.requestWorkspaceSettings("p-0", "connectors");
  assert.equal(link.takeWorkspaceSettingsSection("p-0"), "connectors");
  const content = fs.readFileSync(new URL("../../src/admin/components/projectsTab/ProjectSettingsSectionContent.tsx", import.meta.url), "utf8");
  assert.match(content, /\{focus === "classification" \? classificationCard : null\}\s*<WorkspaceRulesSection/);
  const tab = fs.readFileSync(new URL("../../src/admin/components/AdminProjectsTab.tsx", import.meta.url), "utf8");
  assert.match(tab, /requestWorkspaceSettings\(project\.id, "rules", "classification"\);\s*openSettings\(project\);/);
});
