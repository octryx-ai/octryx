// Principle 01: every visible page says in one sentence what it is for, under its title. Longer text
// belongs in the page help (help/<area>/<page>.md).
import assert from "node:assert/strict";
import { test } from "node:test";

import { ADMIN_AREA_CONFIGS } from "../../src/admin/config/adminPanelAreas.ts";
import { ADMIN_PAGE_PURPOSE } from "../../src/admin/config/pagePurpose.ts";
import { readFileSync } from "node:fs";

const oneSentence = (text) => typeof text === "string" && text.length > 10 && text.length <= 110 && /^[A-Z][^]*\.$/.test(text)
  && text.split(/\.\s/).length === 1;

test("every visible admin page has one short purpose sentence", () => {
  for (const [area, config] of Object.entries(ADMIN_AREA_CONFIGS)) {
    for (const group of config.groups) {
      for (const ref of group.tabs) {
        if (ref.hidden) continue;
        assert.ok(oneSentence(ADMIN_PAGE_PURPOSE[ref.id]), `${area}/${ref.id}: ${ADMIN_PAGE_PURPOSE[ref.id]}`);
      }
    }
  }
});

test("every Work and Coding page has one short purpose sentence", () => {
  for (const file of ["chat/work/WorkNav.tsx", "chat/coding/CodingAreaNav.tsx"]) {
    const source = readFileSync(new URL(`../../src/${file}`, import.meta.url), "utf8");
    const items = [...source.matchAll(/\{ key: "(\w+)", label: "[^"]+", section: "[^"]+"(?:, purpose: "([^"]+)")? \}/g)];
    assert.ok(items.length >= 4, file);
    for (const [, key, purpose] of items) assert.ok(oneSentence(purpose), `${file} ${key}: ${purpose}`);
  }
});
