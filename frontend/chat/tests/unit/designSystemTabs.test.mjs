// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/designSystemTabs.test.mjs
//
// One tab style: every tab-like control is the shared SegmentedTabs. Joined
// segments, underline tabs, pill groups and hand-made tab bars were mixed across the app; this guard fails as soon as
// a new one appears. The rules are in designSystemTabsScan.mjs. Real exceptions (not page views: closable editor file
// tabs, the sheets of a spreadsheet preview) are listed per file, with a reason, in designSystemTabs.allowlist.json;
// the counts may only go down.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import { scanTabs, tabControls } from "./designSystemTabsScan.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.resolve(HERE, "../../src");
const ALLOWLIST = JSON.parse(fs.readFileSync(path.join(HERE, "designSystemTabs.allowlist.json"), "utf8")).files;

const describe = (file, found) => found.map((entry) => `${file}:${entry.line} ${entry.what}`).join("\n");

test("the scanner flags hand-made tabs and leaves other controls alone", () => {
  const source = `export const View = () => (
    <div>
      <div role="tablist"><button role="tab">A</button></div>
      <nav className="admin-channels__tabs" />
      <button className={\`admin-channels__tab\${on ? " admin-channels__tab--active" : ""}\`}>B</button>
      <div className="coding-session-tabs" />
      <nav className="sk-subnav" />
      <div className="runtime-filter-bar__pills" />
      <div className="skills__seg" />
      <div className="connections__tab" />
      <button className="admin-panel__tab admin-panel__tab--active">Menu entry</button>
      <button className="admin-panel__action-btn">Save</button>
      <table className="admin-panel__table" />
    </div>
  );
  const element = createElement("div", { role: "tab" });`;
  const lines = tabControls(source, "View.tsx").map((entry) => entry.line);
  assert.deepEqual(lines, [3, 3, 4, 5, 6, 7, 8, 9, 16]);
});

test("no component renders a tab-like control except through SegmentedTabs", () => {
  const found = scanTabs(SRC);
  const problems = [];
  for (const [file, entries] of found) {
    const allowed = ALLOWLIST[file]?.count ?? 0;
    if (entries.length > allowed) {
      problems.push(`${file}: ${entries.length} tab-like control(s), ${allowed} allowed. Use SegmentedTabs `
        + `(layout/SegmentedTabs.ts; size "small" for the second level, SidePanel's \`tabs\` inside a panel) or, for a `
        + `real exception, raise the allowlist with a reason:\n${describe(file, entries)}`);
    }
  }
  assert.deepEqual(problems, [], problems.join("\n\n"));
});

test("the tab allowlist is current: every entry has a reason and no count is higher than needed", () => {
  const found = scanTabs(SRC);
  const stale = [];
  for (const [file, entry] of Object.entries(ALLOWLIST)) {
    assert.ok(typeof entry.reason === "string" && entry.reason.trim().length > 10, `${file} needs a reason`);
    const actual = found.get(file)?.length ?? 0;
    if (actual < entry.count) stale.push(`${file}: allows ${entry.count}, has ${actual}; lower the count${actual ? "" : " or remove the entry"}`);
  }
  assert.deepEqual(stale, [], stale.join("\n"));
});
