// One date and time format for the whole UI. Day, short month name and year (never
// all-numeric: 10/07/2026 is ambiguous), always 24 h, relative for recent moments, the exact time as tooltip;
// zone-less server times are UTC.
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

import {
  formatClock,
  formatDate,
  formatDateTime,
  formatExactTime,
  formatRecent,
  formatRelative,
  timeOf,
} from "../../src/admin/utils/dateTime.ts";

const NOW = Date.parse("2026-11-05T19:00:00Z");

test("relative wording for recent moments, past and future", () => {
  assert.equal(formatRelative("2026-11-05T18:59:40Z", "—", NOW), "just now");
  assert.equal(formatRelative("2026-11-05T18:49:00Z", "—", NOW), "11 min ago");
  assert.equal(formatRelative("2026-11-05T18:00:01Z", "—", NOW), "59 min ago");
  assert.equal(formatRelative("2026-11-05T16:00:00Z", "—", NOW), "3 h ago");
  assert.equal(formatRelative("2026-11-01T19:00:00Z", "—", NOW), "4 d ago");
  assert.equal(formatRelative("2026-11-05T19:11:00Z", "—", NOW), "in 11 min");
  assert.equal(formatRelative("2026-11-05T22:00:00Z", "—", NOW), "in 3 h");
});

test("a naive server time is UTC", () => {
  assert.equal(formatRelative("2026-11-05T18:49:00", "—", NOW), "11 min ago");
  assert.equal(timeOf("2026-11-05T18:49:00"), Date.parse("2026-11-05T18:49:00Z"));
});

test("older moments and missing values", () => {
  assert.equal(formatRelative("2026-10-07T11:31:07Z", "—", NOW), formatDateTime("2026-10-07T11:31:07Z"));
  assert.equal(formatRelative(null, "—", NOW), "—");
  assert.equal(formatRelative("not a time", "", NOW), "");
  assert.equal(formatDateTime(undefined), "—");
  assert.equal(formatDate("", "never"), "never");
});

test("24-hour clock, day and month name, no AM/PM, never all-numeric", () => {
  const afternoon = "2026-10-07T13:31:07Z";
  for (const text of [formatDateTime(afternoon), formatClock(afternoon), formatExactTime(afternoon)]) {
    assert.doesNotMatch(text, /AM|PM/i, text);
  }
  assert.match(formatDateTime(afternoon), /2026/);
  assert.match(formatDateTime(afternoon), /^7 Oct 2026, \d{2}:31$/, "day, short month name, year, clock");
  assert.equal(formatDate(afternoon), "7 Oct 2026");
  assert.doesNotMatch(formatDateTime(afternoon), /\d{1,2}[./]\d{1,2}[./]\d{2,4}/, "never all-numeric");
  assert.match(formatClock(afternoon), /^\d{2}:\d{2}$/);
  assert.match(formatExactTime(afternoon), /\d{2}:\d{2}:\d{2}/, "the tooltip carries seconds");
  assert.doesNotMatch(formatDate(afternoon), /:/, "a date has no clock");
});

test("no component formats a date with the browser's bare default", () => {
  const root = new URL("../../src/", import.meta.url).pathname;
  const offenders = [];
  const walk = (dir) => {
    for (const name of readdirSync(dir)) {
      const path = join(dir, name);
      if (statSync(path).isDirectory()) walk(path);
      else if (/\.tsx?$/.test(name)) {
        const text = readFileSync(path, "utf8");
        if (/new Date\([^)]*\)\.toLocale(Date|Time)?String\(\)/.test(text) || /\.toLocaleTimeString\(\)/.test(text)) {
          offenders.push(path.slice(root.length));
        }
      }
    }
  };
  walk(root);
  assert.deepEqual(offenders, []);
});

test("list columns use one form: relative up to 7 days, then the date only", () => {
  assert.equal(formatRecent("2026-11-05T05:00:00Z", "—", NOW), "14 h ago");
  assert.equal(formatRecent("2026-11-01T19:00:00Z", "—", NOW), "4 d ago");
  assert.equal(formatRecent("2026-10-15T14:42:00Z", "—", NOW), formatDate("2026-10-15T14:42:00Z"));
  assert.ok(!formatRecent("2026-10-15T14:42:00Z", "—", NOW).includes(":"), "no clock time after a week");
  assert.equal(formatRecent(null, "—", NOW), "—");
});
