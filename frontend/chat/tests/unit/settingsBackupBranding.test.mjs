// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/settingsBackupBranding.test.mjs
//
// Backup/restore preselects nothing destructive and previews the selected
// file; logo uploads go through the inline SVG sanitizer or become a bounded PNG data URL.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  BackupFileError,
  RESTORE_SECTION_OPTIONS,
  backupRestoreFormDefaults,
  parseBackupFile,
  readHistory,
  summarizeBackupFile,
} from "../../src/admin/components/backupRestoreModel.ts";
import {
  MAX_PNG_LOGO_BYTES,
  logoUploadKind,
  pngLogoResult,
  svgLogoResult,
} from "../../src/admin/components/brandingLogoUpload.ts";

test("backup and restore start without a workspace, without overwrite and without platform-wide skills", () => {
  const defaults = backupRestoreFormDefaults();
  assert.equal(defaults.backupProjectId, "");
  assert.equal(defaults.restoreProjectId, "");
  assert.equal(defaults.overwriteExisting, false);
  assert.equal(defaults.overwriteSkills, false);
  assert.deepEqual(defaults.restoreSections, ["project_config", "tasks", "agents"], "skills opt in");
  assert.ok(!RESTORE_SECTION_OPTIONS.some((section) => /knowledge/i.test(section.label)));
});

test("backup files are validated and previewed from their manifest", () => {
  assert.throws(() => parseBackupFile("{"), BackupFileError);
  assert.throws(() => parseBackupFile(JSON.stringify({ export_type: "tasks" })), BackupFileError);
  const payload = parseBackupFile(
    JSON.stringify({
      export_type: "admin_config_backup",
      manifest: {
        format_version: 1,
        included_sections: ["project_config", "tasks", "agents", "skills"],
        excluded_sections: ["sessions", "raw_secrets"],
        secret_policy: "raw secrets are excluded",
      },
      project: { name: "Petclinic", config: {} },
      tasks: [{}, {}],
      agents: [{}],
      skills: [],
    }),
  );
  const preview = summarizeBackupFile(payload);
  assert.equal(preview.workspaceName, "Petclinic");
  assert.equal(preview.formatVersion, "1");
  assert.deepEqual(
    preview.sections.map((section) => [section.id, section.included, section.count]),
    [
      ["project_config", true, null],
      ["tasks", true, 2],
      ["agents", true, 1],
      ["skills", true, 0],
    ],
  );
  assert.deepEqual(preview.excludedSections, ["sessions", "raw_secrets"]);
});

test("the history names who, where and what a restore did to the platform-wide skills (S10)", () => {
  const [restore, backup, failed] = readHistory([
    { kind: "restore", id: "i1", at: "2026-10-08T10:00:00", by: "lena", workspace: "Northwind", status: "completed",
      summary: { project_config_updated: true, task_count: 2, agent_count: 1, skills_created: ["incident"], skills_kept: ["style"] } },
    { kind: "backup", id: "e1", at: "2026-10-08T09:00:00", by: "lena", workspace: "Northwind", status: "completed", downloadable: true,
      summary: { task_count: 2, agent_count: 1, skill_count: 4 } },
    { kind: "backup", id: "e2", status: "failed", error: "Project not found", summary: {} },
  ]);
  assert.equal(restore.result, "configuration restored · 2 actions · 1 agents · skills added: incident · existing skills kept: style");
  assert.equal(backup.result, "2 actions, 1 agents, 4 skills");
  assert.equal(backup.downloadable, true);
  assert.equal(failed.result, "Failed: Project not found");
  assert.deepEqual(readHistory({}), []);
});

test("logo uploads accept SVG through the sanitizer and bounded PNG data URLs", () => {
  assert.equal(logoUploadKind({ name: "logo.SVG", type: "" }), "svg");
  assert.equal(logoUploadKind({ name: "logo.png", type: "image/png" }), "png");
  assert.equal(logoUploadKind({ name: "logo.gif", type: "image/gif" }), null);

  const rejected = svgLogoResult("<svg onload=x>", () => null);
  assert.equal(rejected.ok, false);
  const accepted = svgLogoResult("<svg></svg>", (markup) => `${markup}`);
  assert.deepEqual(accepted, { ok: true, logo_url: "", logo_svg: "<svg></svg>" });

  assert.equal(pngLogoResult("data:image/png;base64,AAAA", MAX_PNG_LOGO_BYTES + 1).ok, false);
  assert.equal(pngLogoResult("data:text/html;base64,AAAA", 10).ok, false);
  assert.deepEqual(pngLogoResult("data:image/png;base64,AAAA", 10), {
    ok: true,
    logo_url: "data:image/png;base64,AAAA",
    logo_svg: "",
  });
});
