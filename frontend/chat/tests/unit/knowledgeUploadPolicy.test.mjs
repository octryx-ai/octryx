import assert from "node:assert/strict";
import { test } from "node:test";
import {
  ACCEPTED_FORMATS,
  ACCEPT_ATTRIBUTE,
  MAX_DOCUMENT_BYTES,
  MAX_TEXT_BYTES,
  acceptedFormatsSummary,
  checkUploadFile,
  formatBytes,
  processingSteps,
  sourceKeyOf,
} from "../../src/admin/components/workspaceKnowledge/knowledgeUploadPolicy.ts";

// backend/app/services/knowledge/ingestion/media_types.py: the stored media types the server accepts.
const SERVER_TEXT = new Set(["text/plain", "text/markdown", "text/asciidoc", "text/csv", "application/json", "application/xml"]);
const SERVER_SANDBOXED = new Set([
  "application/pdf",
  "text/html",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
]);

test("limits mirror the backend bounds", () => {
  assert.equal(MAX_TEXT_BYTES, 8 * 1024 * 1024);
  assert.equal(MAX_DOCUMENT_BYTES, 32 * 1024 * 1024);
  assert.equal(formatBytes(MAX_TEXT_BYTES), "8 MB");
  assert.equal(formatBytes(MAX_DOCUMENT_BYTES), "32 MB");
});

test("every accepted extension maps to a media type the server accepts in the right class", () => {
  for (const format of ACCEPTED_FORMATS) {
    const accepted = format.kind === "text" ? SERVER_TEXT : SERVER_SANDBOXED;
    assert.ok(accepted.has(format.mediaType), `${format.extension} -> ${format.mediaType}`);
    assert.ok(ACCEPT_ATTRIBUTE.split(",").includes(`.${format.extension}`));
  }
  // Every server type is reachable from some extension.
  const mapped = new Set(ACCEPTED_FORMATS.map((format) => format.mediaType));
  for (const type of [...SERVER_TEXT, ...SERVER_SANDBOXED]) assert.ok(mapped.has(type), type);
});

test("the browser's media type is never needed: csv, adoc and md resolve from the extension", () => {
  const csv = checkUploadFile("Report.CSV", 100);
  assert.equal(csv.ok, true);
  assert.equal(csv.format.mediaType, "text/csv");
  assert.equal(checkUploadFile("guide.adoc", 10).format.mediaType, "text/asciidoc");
  assert.equal(checkUploadFile("notes.md", 10).format.mediaType, "text/markdown");
});

test("unknown types, empty files and oversized files are refused before upload", () => {
  const image = checkUploadFile("diagram.png", 100);
  assert.equal(image.ok, false);
  assert.match(image.reason, /not accepted/);
  assert.equal(checkUploadFile("noextension", 100).ok, false);
  assert.equal(checkUploadFile("empty.txt", 0).ok, false);
  const text = checkUploadFile("big.txt", MAX_TEXT_BYTES + 1);
  assert.equal(text.ok, false);
  assert.match(text.reason, /up to 8 MB/);
  assert.equal(checkUploadFile("big.pdf", MAX_TEXT_BYTES + 1).ok, true);
  const pdf = checkUploadFile("huge.pdf", MAX_DOCUMENT_BYTES + 1);
  assert.equal(pdf.ok, false);
  assert.match(pdf.reason, /up to 32 MB/);
});

test("the guide states both classes and the three processing steps", () => {
  const summary = acceptedFormatsSummary();
  assert.deepEqual(summary.map((group) => group.kind), ["document", "text"]);
  assert.ok(summary[0].extensions.includes("pdf") && summary[0].extensions.includes("docx"));
  assert.ok(summary[1].extensions.includes("csv") && !summary[1].extensions.includes("pdf"));
  for (const kind of ["text", "document", null]) {
    const steps = processingSteps(kind);
    assert.equal(steps.length, 3);
    assert.match(steps[0], /^Uploaded/);
    assert.match(steps[1], /^Parsed/);
    assert.match(steps[2], /^Indexed/);
  }
});

test("source keys derive from the file name", () => {
  assert.equal(sourceKeyOf("Spring Boot 4.0 Migration Guide.pdf"), "spring-boot-4.0-migration-guide");
  assert.equal(sourceKeyOf("--weird__name--.md"), "weird__name");
});
