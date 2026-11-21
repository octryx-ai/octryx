// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/chatPhoneLayout.test.mjs
// Phone layout (390 px): a long unbreakable line in an answer never widens the message column past the screen edge,
// and the compact bar's 2rem Octryx button keeps its logo visible (no menu-entry padding).
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { test } from "node:test";

const SRC = path.resolve(path.dirname(new URL(import.meta.url).pathname), "../../src");
const read = (relative) => fs.readFileSync(path.join(SRC, relative), "utf8");

test("the message content is one column no wider than its row", () => {
  const rule = read("styles/chat/message-stream-layout.css").match(/^\.message-row__content \{[^}]*\}/m);
  assert.ok(rule);
  assert.match(rule[0], /grid-template-columns: minmax\(0, 1fr\);/);
  assert.match(rule[0], /min-width: 0;/);
});

test("the compact bar styles only its menu entries, not the Workspace switch or Octryx", () => {
  const css = read("chat/compact-area-menu.css");
  assert.doesNotMatch(css, /\.compact-area-menu button\b/);
  assert.match(css, /\.compact-area-menu nav button \{[^}]*padding: 0?\.75rem 1rem;/);
  assert.match(css, /\.compact-area-menu nav \[aria-current="page"\], \.compact-area-menu nav button:hover/);
});
