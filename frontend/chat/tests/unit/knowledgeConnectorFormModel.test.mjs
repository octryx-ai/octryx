import assert from "node:assert/strict";
import { test } from "node:test";
import { configOf } from "../../src/admin/components/workspaceKnowledge/connectorConfig.ts";
import { reasonText } from "../../src/admin/components/workspaceKnowledge/connectorReasons.ts";
import { initialForm, resetScope, validate } from "../../src/admin/components/workspaceKnowledge/connectorFormModel.ts";
import { gitRunCountsText, gitRunRevision } from "../../src/admin/components/workspaceKnowledge/gitRepositoryReport.ts";
import { gitScopeSummary, isLocalSnapshot } from "../../src/admin/components/workspaceKnowledge/gitRepositoryScope.ts";

const GIT_ONLY = ["fetch_mode", "repository_url", "ref", "include_globs", "exclude_globs", "max_files", "max_file_bytes"];
const OTHER_KINDS_ONLY = ["spaces", "project_keys", "jql", "knowledge_bases", "tables", "article_query", "record_query", "releases"];

function gitForm(patch = {}) {
  return {
    ...initialForm(null),
    ...resetScope("git_repository"),
    key: "boot-docs",
    repositoryUrl: "https://github.com/spring-projects/spring-boot",
    ref: "main",
    ...patch,
  };
}

function problemOf(form) {
  const checked = validate(form);
  assert.ok("problem" in checked, "expected a refusal");
  return checked.problem;
}

const GIT_CONNECTOR = {
  connector_key: "boot-docs",
  kind: "git_repository",
  scope: {
    fetch_mode: "remote_git",
    remote: "https://github.com/spring-projects/spring-boot",
    web_base: "https://github.com/spring-projects/spring-boot",
    ref: "v3.2.0",
    include_globs: ["docs/**/*.adoc", "src/**/*.java"],
    exclude_globs: ["**/test/**"],
    max_files: 2000,
    max_file_bytes: 524288,
  },
  products: ["spring-boot"],
  version: "3.2",
  max_items_per_run: 200,
  state: "active",
  schedule: { enabled: false, interval_minutes: 360, next_run_at: null },
  cursor: { pass_number: 0, token: null, pass_started_at: null, last_completed_at: null, completed_passes: 0 },
  running: false,
  last_run: null,
};

test("a git repository connector sends only its own scope fields, with null for the server defaults", () => {
  const checked = validate(gitForm({ includeGlobs: "src/**/*.java\n\n  docs/**/*.md \nsrc/**/*.java", maxFiles: "", maxFileBytes: "" }));
  assert.ok("config" in checked);
  const { config } = checked;
  assert.equal(config.kind, "git_repository");
  assert.equal(config.fetch_mode, "remote_git");
  assert.equal(config.repository_url, "https://github.com/spring-projects/spring-boot");
  assert.equal(config.ref, "main");
  assert.deepEqual(config.include_globs, ["src/**/*.java", "docs/**/*.md"]);
  assert.equal(config.exclude_globs, null);
  assert.equal(config.max_files, null);
  assert.equal(config.max_file_bytes, null);
  for (const field of OTHER_KINDS_ONLY) assert.ok(!(field in config), `${field} must not be sent for git_repository`);
});

test("other kinds never send the git repository fields", () => {
  const checked = validate({ ...initialForm(null), key: "wiki", keys: "ENG, ARCH" });
  assert.ok("config" in checked);
  assert.deepEqual(checked.config.spaces, ["ENG", "ARCH"]);
  for (const field of GIT_ONLY) assert.ok(!(field in checked.config), `${field} must not be sent for confluence`);
});

test("the repository URL must be https://github.com/<owner>/<repo> exactly", () => {
  assert.match(problemOf(gitForm({ repositoryUrl: "" })), /Enter the repository URL/);
  assert.match(problemOf(gitForm({ repositoryUrl: "http://github.com/a/b" })), /https/);
  assert.match(problemOf(gitForm({ repositoryUrl: "https://gitlab.com/a/b" })), /github\.com/);
  assert.ok("config" in validate(gitForm({ repositoryUrl: "https://bitbucket.org/acme_team/payments" })));
  assert.match(problemOf(gitForm({ repositoryUrl: "https://bitbucket.org/Acme/payments" })),
    /exactly https:\/\/bitbucket\.org\/<workspace>\/<repo>/);
  assert.match(problemOf(gitForm({ repositoryUrl: "https://github.com.evil.example/a/b" })), /github\.com/);
  for (const url of [
    "https://github.com/a/b.git",
    "https://github.com/a/b/",
    "https://github.com/a/b/tree/main",
    "https://github.com/a",
    "https://github.com/a/b?tab=readme",
    "https://github.com/-a/b",
  ]) {
    assert.match(problemOf(gitForm({ repositoryUrl: url })), /exactly https:\/\/github\.com\/<owner>\/<repo>/, url);
  }
});

test("the ref is a branch, tag or sha within the server's character rules", () => {
  for (const ref of ["main", "release/3.2.x", "v3.2.0", "a".repeat(40), "0123456789abcdef0123456789abcdef01234567"]) {
    assert.ok("config" in validate(gitForm({ ref })), ref);
  }
  assert.match(problemOf(gitForm({ ref: " " })), /Enter a ref/);
  for (const ref of ["-main", "/main", "a..b", "feature branch", "x".repeat(101), "main~1"]) {
    assert.match(problemOf(gitForm({ ref })), /The ref is at most 100 characters/, ref);
  }
});

test("globs are bounded in number and length", () => {
  const many = Array.from({ length: 21 }, (_, index) => `dir${index}/**`).join("\n");
  assert.match(problemOf(gitForm({ includeGlobs: many })), /at most 20 include globs/);
  assert.match(problemOf(gitForm({ excludeGlobs: "x".repeat(201) })), /exclude glob is at most 200 characters/);
});

test("the file limits are whole numbers within the server bounds", () => {
  assert.match(problemOf(gitForm({ maxFiles: "0" })), /Max files/);
  assert.match(problemOf(gitForm({ maxFiles: "5001" })), /Max files/);
  assert.match(problemOf(gitForm({ maxFiles: "1.5" })), /Max files/);
  assert.match(problemOf(gitForm({ maxFileBytes: "1023" })), /Max file size/);
  assert.match(problemOf(gitForm({ maxFileBytes: "2097153" })), /Max file size/);
  const checked = validate(gitForm({ maxFiles: "5000", maxFileBytes: "2097152" }));
  assert.ok("config" in checked);
  assert.equal(checked.config.max_files, 5000);
  assert.equal(checked.config.max_file_bytes, 2097152);
});

test("an existing git repository connector loads back from its listed scope and saves unchanged", () => {
  const form = initialForm(GIT_CONNECTOR);
  assert.equal(form.kind, "git_repository");
  assert.equal(form.repositoryUrl, GIT_CONNECTOR.scope.remote);
  assert.equal(form.ref, "v3.2.0");
  assert.equal(form.includeGlobs, "docs/**/*.adoc\nsrc/**/*.java");
  assert.equal(form.excludeGlobs, "**/test/**");
  assert.equal(form.maxFiles, "2000");
  assert.equal(form.maxFileBytes, "524288");
  const checked = validate(form);
  assert.ok("config" in checked);
  assert.deepEqual(checked.config, configOf(GIT_CONNECTOR));
});

test("the scope summary derives owner/repo from the remote and shows the last synced commit", () => {
  const unsynced = gitScopeSummary(GIT_CONNECTOR.scope);
  assert.equal(unsynced.repository, "spring-projects/spring-boot");
  assert.equal(unsynced.ref, "v3.2.0");
  assert.equal(unsynced.include, "docs/**/*.adoc, src/**/*.java");
  assert.equal(unsynced.limits, "at most 2000 files, 512 KiB per file");
  assert.equal(unsynced.head, "not synced yet");
  const head = "0123456789abcdef0123456789abcdef01234567";
  assert.equal(gitScopeSummary({ ...GIT_CONNECTOR.scope, head_commit: head }).head, "synced at 0123456789ab");
  assert.equal(gitScopeSummary({ ...GIT_CONNECTOR.scope, head_commit: head, head_dirty: true }).head, "synced at 0123456789ab (dirty)");
  const snapshotScope = { ...GIT_CONNECTOR.scope, fetch_mode: "local_snapshot", remote: "https://github.com/acme/tools.git", ref: null };
  assert.equal(gitScopeSummary(snapshotScope).repository, "acme/tools");
  assert.equal(gitScopeSummary(snapshotScope).ref, "");
});

test("only a local_snapshot git connector is read-only", () => {
  assert.equal(isLocalSnapshot(GIT_CONNECTOR), false);
  assert.equal(isLocalSnapshot({ ...GIT_CONNECTOR, scope: { ...GIT_CONNECTOR.scope, fetch_mode: "local_snapshot" } }), true);
  assert.equal(isLocalSnapshot({ ...GIT_CONNECTOR, kind: "jira", scope: { fetch_mode: "local_snapshot" } }), false);
});

test("switching the kind clears the git repository fields", () => {
  const reset = resetScope("jira");
  assert.equal(reset.kind, "jira");
  assert.equal(reset.repositoryUrl, "");
  assert.equal(reset.ref, "");
  assert.equal(reset.includeGlobs, "");
  assert.equal(reset.maxFiles, "");
});

test("a git run report shows the per-file outcomes and the short commit", () => {
  const report = {
    created: 4, updated: 1, unchanged: 0, retired: 0, skipped: 9, failed: 0, listed: 14, outcomes_recorded: 14,
    skipped_reasons: { excluded: 5, skipped_binary: 2, skipped_too_large: 1, skipped_empty: 1 },
    repository: { ref: "main", commit: "0123456789abcdef0123456789abcdef01234567" },
  };
  assert.equal(
    gitRunCountsText(report),
    "4 created · 1 updated · 0 unchanged · 5 excluded · 2 skipped binary · 1 skipped too large · 1 skipped empty",
  );
  assert.deepEqual(gitRunRevision(report), { ref: "main", commit: "0123456789ab" });
  assert.equal(gitRunRevision({ created: 0 }), null);
  const odd = { failed: 2, retired: 3, skipped: 4, skipped_reasons: { skipped_unsupported_path: 1, path_too_long: 2 } };
  assert.equal(
    gitRunCountsText(odd),
    "0 created · 0 updated · 0 unchanged · 0 excluded · 0 skipped binary · 0 skipped too large · "
      + "1 skipped unsupported path · 2 skipped path too long · 1 other skipped · 2 failed · 3 retired",
  );
});

test("the git repository refusals have plain-English reasons", () => {
  assert.equal(reasonText("repository_too_large"), "repository exceeds the configured file or size limits");
  assert.equal(reasonText("snapshot_upload_required"), "files arrive with a launcher upload");
});
