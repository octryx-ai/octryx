// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/adminSchedulesLayout.test.mjs
// The schedulers are one full-width DataTable
// whose Name column takes the remaining width; the explanation is the state's tooltip and is spelled out in the
// row's side panel.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

const DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src/admin/components");
const CSS = fs.readFileSync(path.join(DIR, "adminSchedulers.css"), "utf8");
const TAB = ["AdminSchedulersTab.tsx", "scheduler/SchedulerFormPanel.tsx", "scheduler/SchedulerDetailPanel.tsx", "scheduler/schedulerRowWords.tsx"]
  .map((file) => fs.readFileSync(path.join(DIR, file), "utf8")).join("\n");

test("schedulers are a DataTable, not task cards", () => {
  assert.match(TAB, /<DataTable<PanelScheduler>/);
  assert.doesNotMatch(TAB, /className=\{`task-item /);
  assert.doesNotMatch(CSS, /\.admin-scheduler-row/);
});

test("the Name column grows; the other columns keep one line", () => {
  assert.match(TAB, /key: "name",\s+header: "Name",\s+grow: true,/);
  for (const key of ["starts", "runs", "next", "state"]) {
    assert.match(TAB, new RegExp(`key: "${key}",[^}]*?nowrap: true`), key);
  }
});

test("a row opens its side panel; the worker explanation lives there, not in the table", () => {
  assert.match(TAB, /onOpen=\{\(scheduler\) => setOpenId\(scheduler\.id\)\}/);
  assert.match(TAB, /<SchedulerWorkerStatus view=\{worker\} \/>/);
  assert.equal((TAB.match(/<SchedulerWorkerStatus /g) || []).length, 1, "only in the side panel");
});
