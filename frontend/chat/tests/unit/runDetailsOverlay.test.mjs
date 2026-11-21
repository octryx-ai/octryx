// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/runDetailsOverlay.test.mjs
// UX review B: opening "Run details" grew the fixed-height chat header, cut the title off and pushed the
// chips over the first message. The opened body floats below the header instead of taking space inside it.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { readCssWithImports } from "./cssWithImports.mjs";

const CSS = readCssWithImports(path.resolve(path.dirname(new URL(import.meta.url).pathname), "../../src/styles/chat/workspace-shell.css"));

function rule(selector) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = CSS.match(new RegExp(`^${escaped} \\{[^}]*\\}`, "m"));
  assert.ok(match, `${selector} rule exists`);
  return match[0];
}

test("the run details body is an overlay anchored below the header", () => {
  const body = rule(".workspace__run-details-body");
  assert.match(body, /position: absolute;/);
  assert.match(body, /top: calc\(100% \+ [\d.]+rem\);/);
  assert.match(body, /background: var\(--panel\);/);
  assert.doesNotMatch(body, /margin-top/);
});

test("the details element stays unpositioned so the body is not clipped by the scrolling signal row", () => {
  assert.doesNotMatch(rule(".workspace__run-details"), /position:/);
  assert.match(rule(".workspace__header"), /position: sticky;/);
});

// Run details at 390 px: the disclosure sits beside the signal row (which scrolls sideways under a mask on compact
// layouts, a mask that would hide the body), and on phones the body is a sheet across the conversation below the
// header. The meta line ends with "…" instead of a cut.
test("on phones Run details is outside the masked signal row and opens as a sheet below the header", () => {
  const header = fs.readFileSync(path.resolve(path.dirname(new URL(import.meta.url).pathname), "../../src/chat/WorkspaceHeader.tsx"), "utf8");
  // Design review: the disclosure ends the context line, before (and outside) the signal row.
  const details = header.indexOf("<details");
  assert.ok(details > header.indexOf('className="workspace__context-line"'), "the disclosure is in the context line");
  assert.ok(details < header.indexOf('className="workspace__signal-row"'), "the disclosure is not inside the signal row");
  const compact = readCssWithImports(path.resolve(path.dirname(new URL(import.meta.url).pathname), "../../src/styles/chat/chat-compact-shell.css"));
  const sheet = compact.match(/ {2}\.workspace__run-details-body \{[^}]*\}/);
  assert.ok(sheet, "a compact rule for the body");
  assert.match(sheet[0], /left: 0\.7rem;/);
  assert.match(sheet[0], /right: 0\.7rem;/);
  assert.match(sheet[0], /max-height: 60vh;/);
  const meta = compact.match(/ {2}\.workspace__context-line > span \{[^}]*\}/);
  assert.ok(meta, "each part of the meta line ends with an ellipsis itself");
  assert.match(meta[0], /text-overflow: ellipsis;/);
  assert.match(meta[0], /min-width: 0;/);
});
