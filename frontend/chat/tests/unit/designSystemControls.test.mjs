// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/designSystemControls.test.mjs
//
// Design-system guard (Agents area review): no component under src/ may render a raw <select>,
// <textarea>, <button> or text/number/search/radio/checkbox <input> with browser-default styling. The rules are in
// designSystemControlsScan.mjs; the Agents area (src/chat/agents) accepts design-system classes only. Pre-existing
// exceptions are listed per file, with a reason, in designSystemControls.allowlist.json; the counts may only go down.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import { rawControls, scanSources, skinnedClasses } from "./designSystemControlsScan.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.resolve(HERE, "../../src");
const ALLOWLIST = JSON.parse(fs.readFileSync(path.join(HERE, "designSystemControls.allowlist.json"), "utf8")).files;

const describe = (file, found) => found.map((entry) => `${file}:${entry.line} <${entry.tag}${entry.type ? ` type=${entry.type}` : ""}>`).join("\n");

test("the scanner flags raw controls and accepts design-system ones", () => {
  const skins = skinnedClasses(`
    .feature-select { border: 1px solid var(--border); }
    .feature-row button { background: transparent; }
    .only-hover:hover { background: var(--surface-overlay); }
    .layout-only { display: flex; }`);
  const source = `export const View = () => (
    <div>
      <select value="a" />
      <input type="text" className="layout-only" />
      <input type="radio" />
      <button type="button">Raw</button>
      <button type="button" className="only-hover">Hover only</button>
      <input type="file" />
      <input type="hidden" />
      <label className="admin-panel__field"><span>Kind</span><select value="a" /></label>
      <input type="number" className="admin-panel__input" />
      <button type="button" className="admin-panel__action-btn">Save</button>
      <label className="admin-option-card"><input type="radio" /></label>
      <select className="feature-select" />
      <div className="feature-row"><button type="button">Row</button></div>
    </div>
  );`;
  const lax = rawControls(source, "View.tsx", skins).map((entry) => `${entry.line}:${entry.tag}`);
  assert.deepEqual(lax, ["3:select", "4:input", "5:input", "6:button", "7:button"]);
  const strict = rawControls(source, "View.tsx", skins, true).map((entry) => `${entry.line}:${entry.tag}`);
  assert.deepEqual(strict, ["3:select", "4:input", "5:input", "6:button", "7:button", "14:select", "15:button"],
    "in the strict areas a feature class is not enough");
});

test("no component renders a raw control beyond the allowlist", () => {
  const found = scanSources(SRC);
  const problems = [];
  for (const [file, entries] of found) {
    const allowed = ALLOWLIST[file]?.count ?? 0;
    if (entries.length > allowed) {
      problems.push(`${file}: ${entries.length} raw control(s), ${allowed} allowed. Use the design-system classes `
        + `(admin-panel__field, admin-panel__input, admin-users__toolbar-select, admin-panel__action-btn, admin-option-card, `
        + `admin-panel__checkbox) or, for a real exception, raise the allowlist with a reason:\n${describe(file, entries)}`);
    }
  }
  assert.deepEqual(problems, [], problems.join("\n\n"));
});

test("the allowlist is current: every entry has a reason and no count is higher than needed", () => {
  const found = scanSources(SRC);
  const stale = [];
  for (const [file, entry] of Object.entries(ALLOWLIST)) {
    assert.ok(typeof entry.reason === "string" && entry.reason.trim().length > 10, `${file} needs a reason`);
    const actual = found.get(file)?.length ?? 0;
    if (actual < entry.count) stale.push(`${file}: allows ${entry.count}, has ${actual}; lower the count${actual ? "" : " or remove the entry"}`);
  }
  assert.deepEqual(stale, [], stale.join("\n"));
});
