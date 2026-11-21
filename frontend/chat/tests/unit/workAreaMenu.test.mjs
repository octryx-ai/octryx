// Work and Coding are one area with one menu (Plan · Deliver · Code · Configure). Every Work and
// Coding page has exactly one entry, and an entry names the address field that opens it in its host.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { WORK_AREA_ENTRIES, entryViewParam, workAreaGroup, workAreaLabel } from "../../src/chat/work/workAreaMenu.ts";

const keysOf = (file, pattern) => [...readFileSync(new URL(`../../src/${file}`, import.meta.url), "utf8").matchAll(pattern)].map((match) => match[1]);

// E6 (central configuration): pages that left the Work menu. Jira write-back is an entry of Admin › Connections;
// Delivery pipeline was retired and its links redirect. Repositories is back in the menu.
const LEFT_THE_MENU = { work: ["writeback"], coding: ["pipelines"] };

test("every Work and Coding page has exactly one entry, or left the menu on purpose (E6)", () => {
  const work = keysOf("chat/work/WorkNav.tsx", /\{ key: "(\w+)", label:/g).filter((key) => !LEFT_THE_MENU.work.includes(key));
  const coding = keysOf("chat/coding/CodingAreaNav.tsx", /\{ key: "(\w+)", label:/g).filter((key) => !LEFT_THE_MENU.coding.includes(key));
  assert.deepEqual(WORK_AREA_ENTRIES.filter((entry) => entry.host === "work").map((entry) => entry.key).sort(), [...work].sort());
  assert.deepEqual(WORK_AREA_ENTRIES.filter((entry) => entry.host === "coding").map((entry) => entry.key).sort(), [...coding].sort());
  assert.deepEqual([...new Set(WORK_AREA_ENTRIES.map((entry) => entry.group))], ["Plan", "Deliver", "Configure"]);
});

test("entries open their page by address and read as one area", () => {
  assert.deepEqual(entryViewParam({ host: "coding", key: "pipelines" }), { name: "coding_view", value: "pipelines" });
  assert.deepEqual(entryViewParam({ host: "work", key: "intake" }), { name: "work_view", value: "intake" });
  // A Work page opens by the address name the Work area reads back (Plans is `plans`, not its key).
  assert.deepEqual(entryViewParam({ host: "work", key: "changePlans" }), { name: "work_view", value: "plans" });
  assert.deepEqual(entryViewParam({ host: "work", key: "board" }), { name: "work_view", value: "board" });
  assert.equal(workAreaLabel("coding", "sessions"), "Coding sessions");
  assert.equal(workAreaGroup("coding", "rules"), "Configure");
  assert.equal(workAreaGroup("work", "board"), "Plan");
  assert.equal(workAreaLabel("coding", "repositories"), "Repositories");
  assert.equal(workAreaGroup("coding", "repositories"), "Deliver");
});
