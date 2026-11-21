// Concept "Ein Seitenaufbau": one page header for every page. Title and one purpose sentence on the
// left; on the right always Workspace switch, neutral actions, the one primary action, then "?".
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";

import { PageHeader } from "../../src/layout/PageHeader.ts";

const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

test("the right side keeps its order: switch, neutral actions, primary, help", () => {
  let view;
  act(() => {
    view = TestRenderer.create(createElement(PageHeader, {
      eyebrow: "Work · Plan", title: "Work items", purpose: "The Workspace's work items.",
      workspace: createElement("select", { "data-k": "switch" }),
      secondary: createElement("button", { "data-k": "refresh" }, "Refresh"),
      primary: createElement("button", { "data-k": "primary" }, "New item"),
    }));
  });
  const header = view.root.findByProps({ "data-testid": "page-header" });
  const order = header.findAll((node) => typeof node.type === "string" && (node.props["data-k"] || node.props["aria-label"] === "Help for this page"))
    .map((node) => node.props["data-k"] ?? "help");
  assert.deepEqual(order, ["switch", "refresh", "primary", "help"]);
  assert.equal(header.findByType("h1").children.join(""), "Work items");
  act(() => view.unmount());
});

test("every area header is the shared one, with at most one primary action", () => {
  for (const file of ["chat/work/WorkAreaWorkspace.tsx", "chat/coding/CodingAreaWorkspace.tsx", "chat/agents/AgentsAreaWorkspace.tsx", "admin/components/AdminPanelShell.tsx"]) {
    const source = readFileSync(new URL(`../../src/${file}`, import.meta.url), "utf8");
    assert.match(source, /<PageHeader\b/, file);
    assert.doesNotMatch(source, /className="work-area__header"/, `${file} has no own header`);
    assert.ok((source.match(/primary=\{/g) ?? []).length <= 1, `${file}: one primary action`);
  }
});
