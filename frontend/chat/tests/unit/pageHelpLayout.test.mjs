// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/pageHelpLayout.test.mjs
// The open help panel must never cover the page's primary action. On every desktop
// width the page makes room for it (the shell's right padding), a side panel opened meanwhile sits left of it, and on
// narrow screens the help is a sheet over the lower part of the screen, so the page header stays visible.
import assert from "node:assert/strict";
import fs from "node:fs";
import { test } from "node:test";

const CSS = fs.readFileSync(new URL("../../src/styles/chat/page-help.css", import.meta.url), "utf8").replace(/\r\n/g, "\n");

const mediaBlock = (query) => {
  const start = CSS.indexOf(`@media (${query})`);
  assert.ok(start >= 0, `@media (${query}) exists`);
  let depth = 0;
  for (let index = CSS.indexOf("{", start); index < CSS.length; index += 1) {
    if (CSS[index] === "{") depth += 1;
    if (CSS[index] === "}") depth -= 1;
    if (depth === 0) return CSS.slice(start, index + 1);
  }
  return "";
};

test("from the narrowest desktop width on, the page shrinks for the help instead of lying under it", () => {
  const desktop = mediaBlock("min-width: 981px");
  assert.match(desktop, /\.app-shell--help-open \{\s*padding-right: var\(--page-help-width\);/);
  assert.doesNotMatch(CSS, /@media \(min-width: 1[0-9]{3}px\)/, "no wide-screen-only rule: at 1280 and 1440 the help covered the header");
});

test("a side panel opened while help is open stays left of the help", () => {
  const desktop = mediaBlock("min-width: 981px");
  assert.match(desktop, /\.app-shell--help-open \.ds-panel__backdrop \{\s*right: var\(--page-help-width\);/);
});

test("on narrow screens the help is a bottom sheet, so the page header and its actions stay visible", () => {
  const narrow = mediaBlock("max-width: 980px");
  assert.match(narrow, /\.page-help__drawer \{[^}]*align-self: end;[^}]*height: min\(/);
});
