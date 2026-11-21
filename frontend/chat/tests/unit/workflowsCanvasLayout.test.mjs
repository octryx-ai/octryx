// Live judge (1568x755): after A5 moved the flow builder into an `.aw-page`, the builder's `height: 100%`
// resolved against the auto-height grid and the canvas collapsed into a ~70px strip (tiny nodes, the
// "Run & results" toggle over the toolbar). The Workflows page in Canvas view
// takes the admin body's height and hands the canvas the row below the tabs and the toolbar; since designer D2a an
// open workflow takes the whole window.
import assert from "node:assert/strict";
import fs from "node:fs";
import { test } from "node:test";
import { readCssWithImports } from "./cssWithImports.mjs";

const read = (path) => fs.readFileSync(new URL(`../../src/admin/components/${path}`, import.meta.url), "utf8")
  .replace(/\/\*[\s\S]*?\*\//g, "");
const rule = (css, selector) => {
  const start = css.indexOf(`${selector} {`);
  assert.notEqual(start, -1, selector);
  return css.slice(start, css.indexOf("}", start));
};

test("the flow builder fills its parent's height", () => {
  const builder = rule(read("flowBuilder/flowBuilderLayout.css"), ".flow-builder");
  assert.match(builder, /height: 100%/);
  assert.match(builder, /min-height: 0/);
});

test("an open workflow fills the window: a definite height, the canvas its only row, no admin padding or navigation", () => {
  const css = read("agentsWorkflows/agentsWorkflows.css");
  const page = rule(css, ".aw-page--canvas");
  assert.match(page, /(^|[\s;{])height: 100%/);
  // A phone keeps a usable canvas; the page scrolls instead of squashing it.
  assert.match(page, /grid-template-rows: minmax\(24rem, 1fr\)/);
  assert.match(page, /align-content: stretch/);
  assert.match(rule(css, ".admin-panel__body:has(.aw-page--canvas)"), /padding: 0/);
  assert.match(rule(css, ".admin-panel:has(.aw-page--canvas)"), /grid-template-areas: "header" "body"/);
  assert.match(rule(css, ".admin-panel:has(.aw-page--canvas) .admin-panel__sidebar"), /display: none/);
});

test("the Workflows page opens a workflow on its canvas; the separate Canvas page is gone", () => {
  const workflows = read("agentsWorkflows/workflows/WorkflowsPage.tsx");
  assert.match(workflows, /aw-page--canvas/);
  assert.match(workflows, /<FlowWorkflowEditor /);
  assert.match(workflows, /<PhasedWorkflowEditor /);
  assert.equal(fs.existsSync(new URL("../../src/admin/components/agentsWorkflows/canvas/CanvasPage.tsx", import.meta.url)), false);
});

test("the flow canvas may zoom out far enough for fit view to show the whole graph on a 390px screen", () => {
  const canvas = read("flowBuilder/FlowCanvas.tsx") + read("flowBuilder/flowCanvasView.ts");
  assert.match(canvas, /const FLOW_MIN_ZOOM = 0\.2;/);
  assert.match(canvas, /minZoom=\{FLOW_MIN_ZOOM\}/);
  // The diagram of a phase's steps and checks uses the same limits.
  const steps = read("agentsWorkflows/canvas/StepsCanvas.tsx");
  assert.match(steps, /import \{ FIT_VIEW, FLOW_MIN_ZOOM \} from "\.\.\/\.\.\/flowBuilder\/flowCanvasView";/);
  assert.match(steps, /minZoom=\{FLOW_MIN_ZOOM\}/);
});

test("the flow builder's header actions wrap below the title instead of overflowing a 390px screen", () => {
  const actions = rule(readCssWithImports(new URL("../../src/admin/components/flowBuilder/flowBuilderHeaderPanels.css", import.meta.url)), ".flow-builder__header-actions");
  assert.match(actions, /flex-wrap: wrap/);
  assert.match(actions, /min-width: 0/);
  const header = read("flowBuilder/FlowBuilderHeaderActions.tsx");
  assert.doesNotMatch(header, /<button type="button" onClick/, "every header button is a design-system button");
});
