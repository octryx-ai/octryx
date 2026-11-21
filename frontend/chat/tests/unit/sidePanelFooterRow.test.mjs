// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/sidePanelFooterRow.test.mjs
// A side panel without tabs put its body into the tabs row and its footer into the flexible row, so
// "Add connection" filled the whole panel height. Every part has its own row; the footer keeps its buttons small.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { readCssWithImports } from "./cssWithImports.mjs";

const CSS = readCssWithImports(path.resolve(path.dirname(new URL(import.meta.url).pathname), "../../src/styles/chat/design-system.css"));

test("side panel parts keep their grid rows with or without tabs", () => {
  assert.match(CSS, /grid-template-rows: auto auto minmax\(0, 1fr\) auto;/);
  for (const [part, row] of [["header", 1], ["tabs", 2], ["body", 3], ["footer", 4]]) {
    assert.match(CSS, new RegExp(`\\.ds-panel > \\.ds-panel__${part} \\{ grid-row: ${row}; \\}`));
  }
});

test("footer actions are centred, not stretched to the footer height", () => {
  const footer = CSS.match(/^\.ds-panel__footer \{[^}]*\}/m);
  assert.ok(footer, "the footer rule exists");
  assert.match(footer[0], /align-items: center;/);
});
