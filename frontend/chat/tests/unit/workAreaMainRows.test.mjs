// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/workAreaMainRows.test.mjs
// UX review B: Plans and Pull requests showed their empty state under ~640 px of blank space. The work area
// had two grid rows but three children when the problems line showed, so the line took the flexible row.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { test } from "node:test";

const HERE = path.dirname(new URL(import.meta.url).pathname);
const CSS = fs.readFileSync(path.resolve(HERE, "../../src/styles/chat/work-area-main.css"), "utf8");
const WORK = fs.readFileSync(path.resolve(HERE, "../../src/chat/work/WorkAreaWorkspace.tsx"), "utf8");

test("the work area has a row for the optional problems line and pins the body to the flexible row", () => {
  const main = CSS.match(/^\.work-area__main \{[^}]*\}/m);
  assert.ok(main);
  assert.match(main[0], /grid-template-rows: auto auto minmax\(0, 1fr\);/);
  assert.match(CSS, /^\.work-area__main > \.work-area__body \{\s*grid-row: 3;\s*\}/m);
});

test("the problems line sits between the page header and the body", () => {
  const header = WORK.indexOf("<PageHeader");
  const line = WORK.indexOf("<WorkProblemsLine");
  const body = WORK.indexOf('<div className="work-area__body">');
  assert.ok(header > 0 && header < line && line < body);
});
