import assert from "node:assert/strict";
import test from "node:test";
import {
  ENVIRONMENT_FILE_INVALID,
  environmentFileBody,
  environmentFileError,
  environmentFileServerError,
} from "../../src/admin/components/projectsTab/repositories/environmentFileModel.ts";
import { fileStateText, pipelineAuditView } from "../../src/chat/workflowRun/pipelineAuditModel.ts";

test("environment file path follows the server's rules", () => {
  for (const ok of ["", "  ", "coffee/web/claude/.octryx/environment.json", "env.json", `${"a".repeat(195)}.json`]) {
    assert.equal(environmentFileError(ok), null, ok);
  }
  for (const bad of ["/abs/env.json", "a/../env.json", "..", "a\\b.json", "a/env.yaml", "a/.json",
    `${"a".repeat(196)}.json`]) {
    assert.equal(environmentFileError(bad), ENVIRONMENT_FILE_INVALID, bad);
  }
});

test("the body sends the key only when edited, and null clears", () => {
  assert.deepEqual(environmentFileBody("a/.octryx/e.json", "a/.octryx/e.json "), {});
  assert.deepEqual(environmentFileBody(null, ""), {});
  assert.deepEqual(environmentFileBody(null, " b/.octryx/e.json"), { environment_file: "b/.octryx/e.json" });
  assert.deepEqual(environmentFileBody("a/.octryx/e.json", "  "), { environment_file: null });
});

test("the server's 422 maps to the field, other errors do not", () => {
  assert.equal(environmentFileServerError(Object.assign(new Error("x"), { code: "invalid_environment_file" })),
    ENVIRONMENT_FILE_INVALID);
  assert.equal(environmentFileServerError(Object.assign(new Error("x"), { code: "forbidden" })), null);
  assert.equal(environmentFileServerError(null), null);
});

const FILE_AUDIT = { source: "environment_file", file: "coffee/web/claude/.octryx/environment.json",
  app_folder: "coffee/web/claude", sha256: "ab".repeat(32), head: "1234567890abcdef", tree: "t".repeat(40) };

test("a green file run names the file, the head and folds the commands and folder", () => {
  const view = pipelineAuditView({ state: "green", audit: { ...FILE_AUDIT, file_state: "ok",
    commands: ["pytest -q", "npx playwright test"] } });
  assert.equal(view.summary, "Ran 2 commands from coffee/web/claude/.octryx/environment.json @ 1234567");
  assert.equal(view.label, "Passed");
  assert.equal(view.problem, null);
  assert.deepEqual(view.errors, []);
  assert.ok(view.details.includes("$ pytest -q"));
  assert.ok(view.details.includes("Folder: coffee/web/claude"));
});

test("a record run says so; no audit shows nothing", () => {
  const view = pipelineAuditView({ state: "red", audit: { source: "repository_record", commands: ["make test"] } });
  assert.equal(view.summary, "Ran 1 command from the repository record");
  assert.equal(view.tone, "problem");
  assert.equal(view.problem, null);
  assert.equal(pipelineAuditView({ state: "pending", audit: null }), null);
  assert.equal(pipelineAuditView(null), null);
});

test("red file states are in words with errors and only the failed setup lines", () => {
  const missing = pipelineAuditView({ state: "red", audit: { ...FILE_AUDIT, commands: [], file_state: "missing",
    file_errors: ["no such file"] } });
  assert.match(missing.problem, /is not in the run's branch/);
  assert.equal(missing.summary, "No commands ran from coffee/web/claude/.octryx/environment.json @ 1234567");
  assert.deepEqual(missing.errors, ["no such file"]);
  assert.match(fileStateText({ ...FILE_AUDIT, file_state: "invalid" }), /not a valid environment file/);
  const setup = pipelineAuditView({ state: "red", audit: { ...FILE_AUDIT, commands: [], file_state: "setup_failed",
    setup: [{ command: "uv sync", exit_code: 0 }, { command: "npm ci", exit_code: 1, output_end: "ERR! lock" }] } });
  assert.match(setup.problem, /failed in coffee\/web\/claude\//);
  assert.deepEqual(setup.setup, ["$ npm ci\nexit 1\nERR! lock"]);
});
