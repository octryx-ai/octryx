import assert from "node:assert/strict";
import { test } from "node:test";
import {
  MAX_PATTERN_CHARS,
  MAX_REASON_CHARS,
  existingEntry,
  mayDecideSource,
  modeExplanation,
  normalizeSourcePattern,
  patternProblem,
  redecisionWarning,
} from "../../src/chat/knowledge/researchSourcePresenter.ts";

const source = (pattern, state, scope = "workspace") => ({
  id: pattern, scope, pattern, products: [], state, origin: "admin", reason: "", evidence_url: null,
  decided_at: null, created_at: null,
});

test("input bounds match the backend request model", () => {
  assert.equal(MAX_PATTERN_CHARS, 300);
  assert.equal(MAX_REASON_CHARS, 500);
  assert.match(patternProblem("a".repeat(301)), /at most 300/);
});

test("patterns normalize like the server stores them", () => {
  assert.equal(normalizeSourcePattern("https://WWW.Docs.Spring.io/"), "docs.spring.io");
  assert.equal(normalizeSourcePattern("github.com/spring-projects//spring-boot/"), "github.com/spring-projects/spring-boot");
  assert.equal(normalizeSourcePattern("localhost"), null);
  assert.equal(normalizeSourcePattern("ftp://docs.spring.io"), null);
  assert.equal(normalizeSourcePattern("https://user:pw@docs.spring.io"), null);
  assert.match(patternProblem("docs.example.org/*"), /Wildcards/);
  assert.equal(patternProblem("docs.spring.io"), null);
});

test("re-adding an existing pattern warns that it re-decides it", () => {
  const sources = [source("docs.spring.io", "blocked"), source("spring.io", "trusted", "platform")];
  const existing = existingEntry(sources, "https://www.docs.spring.io/", "workspace");
  assert.equal(existing?.id, "docs.spring.io");
  assert.match(redecisionWarning(existing, "trusted"), /currently blocked\. Saving changes the decision to approved/);
  assert.match(redecisionWarning(existing, "blocked"), /already blocked/);
  // Another scope is another entry.
  assert.equal(existingEntry(sources, "spring.io", "workspace"), null);
  assert.equal(redecisionWarning(null, "trusted"), null);
});

test("platform entries need the platform role, workspace entries the author role", () => {
  assert.equal(mayDecideSource(source("a.io", "proposed"), true, false), true);
  assert.equal(mayDecideSource(source("a.io", "proposed", "platform"), true, false), false);
  assert.equal(mayDecideSource(source("a.io", "proposed", "platform"), true, true), true);
  assert.equal(mayDecideSource(source("a.io", "proposed"), false, true), false);
});

test("both search modes are explained", () => {
  assert.match(modeExplanation("trusted_only"), /Approved websites only/);
  assert.match(modeExplanation("open"), /except blocked/);
});
