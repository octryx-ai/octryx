import { useEffect, useState } from "react";

import "../../restApis/restApis.css"; // rst-field__error: the one field-level error line

import {
  ENVIRONMENT_FILE_HINT,
  ENVIRONMENT_FILE_KEY,
  ENVIRONMENT_FILE_LABEL,
  ENVIRONMENT_FILE_PLACEHOLDER,
  environmentFileBody,
  environmentFileError,
  environmentFileServerError,
  environmentFileText,
} from "./environmentFileModel";
import { loadCodingSetup, saveCodingSetup, sourceText, type CodingSetup, type WorkspaceRepository } from "./workspaceRepositoriesApi";

// The one placeholder vocabulary of branch rules (backend source_control/branch_naming.py); alias names work.
export const BRANCH_RULE_HINT =
  "Placeholders: {type} (feature, bugfix), {key} (the ticket key), {slug} (the title). Empty: {type}/{key}-{slug}.";

// One repository record: Source · Branches · Owners · Coding setup. The record's source and default branch come
// from its Knowledge source; everything the agent needs to build, test and lint it is edited here and only here.
const GROUPS: Array<{ title: string; fields: Array<{ key: string; label: string; list: boolean; hint?: string }> }> = [
  { title: "Branches", fields: [
    { key: "branch_naming_rule", label: "Branch naming rule", list: false, hint: BRANCH_RULE_HINT },
    { key: "pr_target_branch", label: "Pull request target branch", list: false },
    { key: "protected_branches", label: "Protected branches", list: true },
  ] },
  { title: "Owners", fields: [
    { key: "owners", label: "Owners", list: true },
    { key: "default_reviewers", label: "Default reviewers", list: true },
  ] },
  { title: "Coding setup", fields: [
    { key: "setup_commands", label: "Setup commands", list: true },
    { key: "build_commands", label: "Build commands", list: true },
    { key: "test_commands", label: "Test commands", list: true },
    { key: "lint_commands", label: "Lint commands", list: true },
    { key: "format_commands", label: "Format commands", list: true },
    { key: "local_toolchain", label: "Toolchain", list: true },
    { key: "builder_runtime_image", label: "Builder image", list: false },
    { key: "required_env_vars", label: "Required environment variables", list: true },
    { key: "secret_references", label: "Secret references", list: true },
    { key: "test_report_paths", label: "Test report paths", list: true },
    { key: "coverage_report_paths", label: "Coverage report paths", list: true },
  ] },
];

const asText = (value: unknown, list: boolean) =>
  list ? (Array.isArray(value) ? value.map(String).join("\n") : "") : typeof value === "string" ? value : "";

// The PUT body: every field (a list field one entry per line), plus the environment file when it changed.
function setupPayload(draft: Record<string, string>, setup: CodingSetup | null, environmentFile: string): CodingSetup {
  const payload: CodingSetup = {};
  for (const field of GROUPS.flatMap((group) => group.fields)) {
    const value = draft[field.key] ?? "";
    payload[field.key] = field.list ? value.split("\n").map((line) => line.trim()).filter(Boolean) : value.trim();
  }
  Object.assign(payload, environmentFileBody(setup?.[ENVIRONMENT_FILE_KEY], environmentFile));
  return payload;
}

// A loaded setup fills the record, the environment file field and the draft of every field.
function applyLoadedSetup(next: CodingSetup, set: {
  setSetup: (setup: CodingSetup) => void;
  setEnvironmentFile: (value: string) => void;
  setDraft: (draft: Record<string, string>) => void;
}) {
  set.setSetup(next);
  set.setEnvironmentFile(environmentFileText(next[ENVIRONMENT_FILE_KEY]));
  set.setDraft(Object.fromEntries(GROUPS.flatMap((group) => group.fields).map((field) => [field.key, asText(next[field.key], field.list)])));
}

// Why a save failed; a refused environment file is also marked at its field.
function saveFailureText(error: unknown, setEnvironmentFileRefused: (refused: string) => void): string {
  const refused = environmentFileServerError(error);
  if (refused) setEnvironmentFileRefused(refused);
  return refused ? "Could not save: check the environment file."
    : error instanceof Error ? error.message : "Could not save the coding setup.";
}

function RecordHeader({ repository, onClose }: { repository: WorkspaceRepository; onClose: () => void }) {
  return (
    <>
      <div className="admin-panel__section-header">
        <span>Repository · {repository.name}</span>
        <button type="button" className="admin-panel__action-btn" onClick={onClose}>Close</button>
      </div>
      <dl className="work-detail__kv">
        <dt>Source</dt><dd>{sourceText(repository.source)}</dd>
        <dt>Default branch</dt><dd className="work-mono">{repository.default_branch || "–"}</dd>
      </dl>
    </>
  );
}

export function RepositoryCodingSetup({ workspaceId, repository, onSaved, onClose }: {
  workspaceId: string;
  repository: WorkspaceRepository;
  onSaved: () => void;
  onClose: () => void;
}) {
  const [setup, setSetup] = useState<CodingSetup | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [environmentFile, setEnvironmentFile] = useState("");
  const [environmentFileRefused, setEnvironmentFileRefused] = useState<string | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    let active = true;
    loadCodingSetup(workspaceId, repository.id).then((next) => {
      if (!active) return;
      applyLoadedSetup(next, { setSetup, setEnvironmentFile, setDraft });
    }).catch((error) => active && setMessage({ ok: false, text: error instanceof Error ? error.message : "Could not load the coding setup." }));
    return () => { active = false; };
  }, [workspaceId, repository.id]);

  const environmentFileProblem = environmentFileError(environmentFile) ?? environmentFileRefused;

  async function save() {
    if (environmentFileError(environmentFile)) return;
    setBusy(true);
    setEnvironmentFileRefused(null);
    setMessage(null);
    const payload = setupPayload(draft, setup, environmentFile);
    try {
      await saveCodingSetup(workspaceId, repository.id, payload);
      setSetup((current) => ({ ...(current ?? {}), [ENVIRONMENT_FILE_KEY]: environmentFile.trim() || null }));
      setMessage({ ok: true, text: "Saved the coding setup." });
      onSaved();
    } catch (error) {
      setMessage({ ok: false, text: saveFailureText(error, setEnvironmentFileRefused) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="admin-panel__card" aria-label={`Repository ${repository.name}`} data-testid="repository-record">
      <RecordHeader repository={repository} onClose={onClose} />
      {!setup ? <p className="admin-panel__hint">Loading the coding setup…</p> : GROUPS.map((group) => (
        <SetupGroup key={group.title} group={group} draft={draft} setDraft={setDraft} environmentFile={environmentFile}
          environmentFileProblem={environmentFileProblem}
          onEnvironmentFile={(value) => { setEnvironmentFile(value); setEnvironmentFileRefused(null); }} />
      ))}
      <p className="admin-panel__hint">One entry per line. Work and Coding read this record; they never declare a repository themselves.</p>
      <div className="admin-inline-actions">
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" disabled={busy || !setup || Boolean(environmentFileError(environmentFile))}
          onClick={() => void save()}>{busy ? "Saving…" : "Save coding setup"}</button>
      </div>
      {message ? <p className={message.ok ? "admin-panel__hint" : "admin-panel__error"} role={message.ok ? "status" : "alert"}>{message.text}</p> : null}
    </section>
  );
}

// One group of the record; Coding setup starts with the environment file.
function SetupGroup({ group, draft, setDraft, environmentFile, environmentFileProblem, onEnvironmentFile }: {
  group: (typeof GROUPS)[number];
  draft: Record<string, string>;
  setDraft: (next: Record<string, string>) => void;
  environmentFile: string;
  environmentFileProblem: string | null;
  onEnvironmentFile: (value: string) => void;
}) {
  return (
    <div className="admin-modal__stack">
      <div className="admin-panel__section-header"><span>{group.title}</span></div>
      <div className="admin-panel__form-grid">
        {group.title === "Coding setup" ? (
          <label className="admin-panel__field" data-testid="repository-environment-file">
            <span>{ENVIRONMENT_FILE_LABEL}</span>
            <input value={environmentFile} aria-label={ENVIRONMENT_FILE_LABEL} placeholder={ENVIRONMENT_FILE_PLACEHOLDER}
              className="work-mono" spellCheck={false} aria-invalid={environmentFileProblem ? true : undefined}
              aria-describedby="repository-environment-file-hint"
              onChange={(event) => onEnvironmentFile(event.target.value)} />
            {environmentFileProblem
              ? <span className="rst-field__error" role="alert">{environmentFileProblem}</span> : null}
            <span className="admin-panel__hint" id="repository-environment-file-hint">{ENVIRONMENT_FILE_HINT}</span>
          </label>
        ) : null}
        {group.fields.map((field) => (
          <label key={field.key} className="admin-panel__field">
            <span>{field.label}</span>
            {field.list ? (
              <textarea rows={2} value={draft[field.key] ?? ""} aria-label={field.label}
                onChange={(event) => setDraft({ ...draft, [field.key]: event.target.value })} />
            ) : (
              <input value={draft[field.key] ?? ""} aria-label={field.label}
                onChange={(event) => setDraft({ ...draft, [field.key]: event.target.value })} />
            )}
            {field.hint ? <span className="admin-panel__hint">{field.hint}</span> : null}
          </label>
        ))}
      </div>
    </div>
  );
}
