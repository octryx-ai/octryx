// Judge 1031px layout fixes (workflow details panel and disabled palette entries):
// the CSS must size by the available container, not by fixed minimums, and keep reasons readable.
import assert from "node:assert/strict";
import fs from "node:fs";
import { test } from "node:test";
import { readCssWithImports } from "./cssWithImports.mjs";

const read = (path) => readCssWithImports(new URL(`../../src/admin/components/${path}`, import.meta.url))
  .replace(/\/\*[\s\S]*?\*\//g, "").replace(/\r\n/g, "\n");
const rule = (css, selector) => {
  const start = css.indexOf(`${selector} {`);
  assert.notEqual(start, -1, selector);
  return css.slice(start, css.indexOf("}", start));
};

test("workflow details fields fit the panel: name and key share a row, description takes its own", () => {
  const css = read("flowBuilder/flowEditorDetails.css");
  assert.match(fs.readFileSync(new URL("../../src/admin/components/flowBuilder/AdminFlowBuilderTab.tsx", import.meta.url), "utf8"),
    /import "\.\/flowEditorDetails\.css";/);
  const grid = rule(css, ".flow-builder__details-grid");
  assert.match(grid, /repeat\(auto-fit, minmax\(min\(100%, 12rem\), 1fr\)\)/);
  assert.doesNotMatch(grid, /minmax\(260px/);
  assert.match(rule(css, ".flow-builder__details-description"), /grid-column: 1 \/ -1/);
});

// Only the palette's own rules; whether the button really renders at full opacity is decided by the whole
// cascade and is asserted in flowPaletteDisabledCascade.test.mjs.
test("the palette's own disabled-entry rules set no dimming and style the reason", () => {
  const css = read("flowBuilder/flowBuilderWorkbench.css");
  const disabled = rule(css, ".flow-palette__item--disabled,\n.flow-palette__item--disabled:hover");
  assert.doesNotMatch(disabled, /opacity/);
  assert.match(disabled, /cursor: not-allowed/);
  const palette = read("flowBuilder/flowPalette.css");
  assert.match(rule(palette, ".flow-palette .flow-palette__item--disabled .flow-palette__item-main small"), /color: var\(--muted-strong\)/);
});
