// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/sidePanelSurface.test.mjs
// In the light theme a side panel let the page show through (its surface gradient is 96 % opaque),
// and at 390 px the connection panel was wider than the screen (a long tab row widened its one grid column).
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { readCssWithImports } from "./cssWithImports.mjs";

const STYLES = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src/styles/chat");
const DS = readCssWithImports(path.join(STYLES, "design-system.css"));
const TOKENS = fs.readFileSync(path.join(STYLES, "ds-tokens.css"), "utf8");
const THEME = fs.readFileSync(path.join(STYLES, "theme-tokens.css"), "utf8");
const panel = DS.match(/^\.ds-panel \{[^}]*\}/m)?.[0] ?? "";

test("the side panel is opaque in both themes", () => {
  assert.match(panel, /background: var\(--ds-surface\);\s*background-color: var\(--ds-panel-backing\);/);
  assert.match(TOKENS, /--ds-panel-backing: var\(--bg\);/);
  const bgs = [...THEME.matchAll(/^\s*--bg: ([^;]+);/gm)].map((match) => match[1]);
  assert.equal(bgs.length, 2, "dark and light define the page colour");
  for (const bg of bgs) assert.match(bg, /^#[0-9a-f]{6}$/i, `${bg} is an opaque colour`);
});

test("the panel never gets wider than the screen", () => {
  assert.match(panel, /grid-template-columns: minmax\(0, 1fr\);/);
  assert.match(panel, /max-width: 100vw;/);
});
