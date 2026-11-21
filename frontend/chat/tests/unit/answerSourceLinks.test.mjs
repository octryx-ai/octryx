import assert from "node:assert/strict";
import { test } from "node:test";
import { safeSourceUrl, collectAnswerSources } from "../../src/chat/evidence/answerSourceLinks.ts";
const origin = "http://localhost:8092";
test("source URLs preserve line/page anchors and governed evidence links", () => {
  assert.equal(safeSourceUrl("https://example.org/code#L10-L20", origin), "https://example.org/code#L10-L20");
  assert.equal(safeSourceUrl("/api/v1/workspaces/a/knowledge/evidence/e", origin), `${origin}/api/v1/workspaces/a/knowledge/evidence/e`);
});
test("executable, relative artifact and credential-bearing links are excluded", () => {
  for (const url of ["javascript:alert(1)", "data:text/plain,test", "/other-turn", "//evil.org", "https://u:p@example.org", "https://example.org?access_token=secret", "https://example.org?X-Amz-Signature=secret"]) {
    assert.equal(safeSourceUrl(url, origin), null, url);
  }
});
function link(url, label, statement) { return { getAttribute: () => url, textContent: label, closest: () => ({ textContent: statement }) }; }
test("collection stays in the answer Markdown, deduplicates and retains distinct locations", () => {
  const article = { querySelectorAll(selector) {
    assert.equal(selector, ".message-markdown a[href]");
    return [link("https://example.org#L1", "Source", "First claim"), link("https://example.org#L1", "Source", "Repeated"), link("https://example.org#L2", "Source", "Second claim")];
  } };
  const result = collectAnswerSources(article, origin);
  assert.equal(result.sources.length, 2);
  assert.equal(result.sources[0].statement, "First claim");
});
test("empty answers and bounded overviews are explicit", () => {
  assert.deepEqual(collectAnswerSources(null, origin), { sources: [], excluded: 0, truncated: false });
  const result = collectAnswerSources({ querySelectorAll: () => Array.from({ length: 101 }, (_, i) => link(`https://example.org/${i}`, "x".repeat(500), "s".repeat(2000))) }, origin);
  assert.equal(result.sources.length, 100); assert.equal(result.truncated, true);
  assert.equal(result.sources[0].label.length, 300); assert.equal(result.sources[0].statement.length, 600);
});

test("the compact list names the kind of source and previews long statements", async () => {
  const { describeSource, previewStatement } = await import("../../src/chat/evidence/answerSourceLinks.ts");
  assert.equal(describeSource(`${origin}/api/v1/workspaces/w/knowledge-evidence/sources/s/revisions/r/original`, origin).kind, "knowledge");
  assert.equal(describeSource("https://docs.spring.io/spring-boot/reference.html?x=1", origin).location, "docs.spring.io/spring-boot/reference.html");
  const long = "word ".repeat(80);
  assert.ok(previewStatement(long).length <= 180);
  assert.ok(previewStatement(long).endsWith("…"));
  assert.equal(previewStatement("Short  statement"), "Short statement");
});

test("the same address cited under different labels counts as one source", () => {
  const result = collectAnswerSources({ querySelectorAll: () => [
    link("https://example.org/guide", "Spring guide", "First claim"),
    link("https://example.org/guide", "the guide", "Second claim"),
    link("https://example.org/guide#L5", "Spring guide", "Anchored claim"),
  ] }, origin);
  assert.deepEqual(result.sources.map((source) => [source.url, source.label, source.statement]), [
    ["https://example.org/guide", "Spring guide", "First claim"],
    ["https://example.org/guide#L5", "Spring guide", "Anchored claim"],
  ]);
});
