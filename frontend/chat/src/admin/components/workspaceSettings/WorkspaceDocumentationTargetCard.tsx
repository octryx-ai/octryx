import { useEffect, useId, useState } from "react";

import { readJson } from "../../../chat/chatApiClient";
import { connectorsApi } from "../workspaceKnowledge/connectorsApi";
import { ToggleRow } from "../settingsKit/SettingsKit";
import {
  AUTO_PUBLISH_HINT,
  confluenceSources,
  docTargetBody,
  docTargetProblems,
  docTargetSaveErrors,
  docTargetWarnings,
  DOC_TARGET_INTRO,
  EMPTY_DOC_TARGET,
  offeredSpaces,
  PARENT_HINT,
  readDocTarget,
  sameDocTarget,
  type ConfluenceSource,
  type DocTarget,
  type DocTargetErrors,
} from "./documentationTargetModel";

const configPath = (projectId: string) => `/api/v1/projects/${encodeURIComponent(projectId)}/config`;

/** The PUT keeps a refusal's status and body, so the card can put it at its field. */
async function saveConfig(projectId: string, body: unknown): Promise<{ ok: boolean; status: number; body: unknown }> {
  const response = await fetch(configPath(projectId), {
    method: "PUT",
    credentials: "same-origin",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  let payload: unknown = null;
  try { payload = await response.json(); } catch { /* an answer without JSON keeps its status */ }
  return { ok: response.ok, status: response.status, body: payload };
}

/** The stored target and whether this person may change it: the config route is admin-only; members read the
 * Workspace's config from their Workspace list. */
async function loadTarget(projectId: string, isAdmin: boolean): Promise<{ target: DocTarget; canEdit: boolean }> {
  if (isAdmin) {
    try {
      return { target: readDocTarget(await readJson<unknown>(configPath(projectId))), canEdit: true };
    } catch (error) {
      if ((error as { status?: number }).status !== 403) throw error;
    }
  }
  const projects = await readJson<{ id: string; config?: unknown }[]>("/api/v1/projects");
  const project = projects.find((entry) => entry.id === projectId);
  return { target: readDocTarget(project?.config ?? {}), canEdit: false };
}

/** The PUT of the target: the stored target, or the refusal at its fields (a request that never arrives is general). */
async function saveDocTarget(projectId: string, draft: DocTarget): Promise<{ next: DocTarget; errors?: undefined } | { next?: undefined; errors: DocTargetErrors }> {
  try {
    const result = await saveConfig(projectId, docTargetBody(draft));
    if (result.ok) return { next: readDocTarget(result.body) };
    return { errors: docTargetSaveErrors(result.status, result.body) };
  } catch {
    return { errors: { general: "Not saved: the request did not reach the server." } };
  }
}

type LoadSetters = {
  setStored: (target: DocTarget | null) => void;
  setDraft: (target: DocTarget) => void;
  setCanEdit: (canEdit: boolean) => void;
  setSources: (sources: ConfluenceSource[]) => void;
  setLoadProblem: (problem: string | null) => void;
};

// Loads the stored target and the Workspace's Confluence sources whenever the Workspace or the role changes.
function useDocTargetLoad(projectId: string, isAdmin: boolean, setters: LoadSetters) {
  const { setStored, setDraft, setCanEdit, setSources, setLoadProblem } = setters;
  useEffect(() => {
    let current = true;
    setStored(null);
    setLoadProblem(null);
    loadTarget(projectId, isAdmin).then(({ target, canEdit: editable }) => {
      if (!current) return;
      setStored(target);
      setDraft(target);
      setCanEdit(editable);
    }).catch(() => { if (current) setLoadProblem("The documentation target could not be loaded."); });
    connectorsApi.list(projectId)
      .then((answer) => { if (current) setSources(confluenceSources(answer.connectors ?? [])); })
      .catch(() => undefined);
    return () => { current = false; };
  }, [projectId, isAdmin, setStored, setDraft, setCanEdit, setSources, setLoadProblem]);
}

// Workspace settings › Knowledge › "Documentation target": where runs publish feature documentation in Confluence
// (project config `feature_documentation`). Admins change it with Save; everyone else reads it.
export function WorkspaceDocumentationTargetCard({ projectId, isAdmin }: { projectId: string; isAdmin: boolean }) {
  const [stored, setStored] = useState<DocTarget | null>(null);
  const [draft, setDraft] = useState<DocTarget>(EMPTY_DOC_TARGET);
  const [canEdit, setCanEdit] = useState(false);
  const [sources, setSources] = useState<ConfluenceSource[]>([]);
  const [loadProblem, setLoadProblem] = useState<string | null>(null);
  const [errors, setErrors] = useState<DocTargetErrors>({});
  const [saved, setSaved] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const id = useId();

  useDocTargetLoad(projectId, isAdmin, { setStored, setDraft, setCanEdit, setSources, setLoadProblem });

  if (loadProblem) return <section className="admin-panel__card"><p className="sk-err" role="alert">{loadProblem}</p></section>;
  if (!stored) return null;

  const problems = docTargetProblems(draft);
  const changed = !sameDocTarget(draft, stored);
  const editable = canEdit && !busy;
  const shown = { ...errors, ...(changed ? problems : {}) };
  const warning = shown.parentPageId ? null : docTargetWarnings(draft).parentPageId ?? null;
  const spaces = offeredSpaces(sources, draft.connectorKey);
  const unknownSource = draft.connectorKey && !sources.some((source) => source.key === draft.connectorKey);
  const edit = (patch: Partial<DocTarget>) => { setDraft((current) => ({ ...current, ...patch })); setErrors({}); setSaved(null); };

  async function save() {
    if (Object.keys(problems).length) return;
    setBusy(true);
    setErrors({});
    setSaved(null);
    const outcome = await saveDocTarget(projectId, draft);
    if (outcome.next) {
      setStored(outcome.next);
      setDraft(outcome.next);
      setSaved(outcome.next.spaceKey ? "Saved. Runs from now on publish here." : "Saved. Runs publish no documentation page until a space is named.");
    } else {
      setErrors(outcome.errors);
    }
    setBusy(false);
  }

  return (
    <section className="admin-panel__card" aria-label="Documentation target" data-testid="workspace-doc-target">
      <div className="admin-panel__section-header"><span>Documentation target</span></div>
      <p className="sk-muted" data-testid="doc-target-intro">{DOC_TARGET_INTRO}</p>
      <DocTargetFields id={id} draft={draft} shown={shown} warning={warning} spaces={spaces} sources={sources}
        unknownSource={Boolean(unknownSource)} editable={editable} edit={edit} />
      <ToggleRow title="Publish automatically" sub={AUTO_PUBLISH_HINT} on={draft.autoPublish} disabled={!editable}
        testId="doc-target-auto-publish" onChange={(next) => edit({ autoPublish: next })} />
      <FieldError text={shown.autoPublish} />
      {canEdit && changed ? (
        <DocTargetActions busy={busy} blocked={Object.keys(problems).length > 0}
          onDiscard={() => { setDraft(stored); setErrors({}); }} onSave={() => void save()} />
      ) : null}
      {canEdit ? null : <p className="sk-muted" data-testid="doc-target-readonly">Only a platform admin can change this.</p>}
      {shown.general ? <p className="sk-err" role="alert">{shown.general}</p> : null}
      {saved ? <p className="admin-panel__success" role="status">{saved}</p> : null}
    </section>
  );
}

function FieldError({ text }: { text?: string }) {
  return text ? <p className="sk-err" role="alert">{text}</p> : null;
}

function DocTargetFields({ id, draft, shown, warning, spaces, sources, unknownSource, editable, edit }: {
  id: string;
  draft: DocTarget;
  shown: DocTargetErrors;
  warning: string | null;
  spaces: string[];
  sources: ConfluenceSource[];
  unknownSource: boolean;
  editable: boolean;
  edit: (patch: Partial<DocTarget>) => void;
}) {
  return (
    <div className="admin-form-grid">
      <label className="admin-panel__field">
        <span>Space key</span>
        <input className="admin-panel__input" value={draft.spaceKey} list={`${id}-spaces`} placeholder="e.g. ENG"
          disabled={!editable} aria-invalid={shown.spaceKey ? true : undefined} data-testid="doc-target-space"
          onChange={(event) => edit({ spaceKey: event.target.value })} />
        <datalist id={`${id}-spaces`}>{spaces.map((space) => <option key={space} value={space} />)}</datalist>
        <span className="sk-muted">{spaces.length ? `Spaces your Knowledge sources read: ${spaces.join(", ")}.` : "The key in the space's address (…/spaces/ENG/…)."}</span>
        <FieldError text={shown.spaceKey} />
      </label>
      <label className="admin-panel__field">
        <span>Parent page id <span className="sk-muted">(required)</span></span>
        <input className="admin-panel__input" value={draft.parentPageId} inputMode="numeric" placeholder="e.g. 123456789"
          disabled={!editable} required aria-required="true" aria-invalid={shown.parentPageId || warning ? true : undefined}
          data-testid="doc-target-parent" onChange={(event) => edit({ parentPageId: event.target.value })} />
        <span className="sk-muted">{PARENT_HINT}</span>
        <FieldError text={shown.parentPageId} />
        {warning ? <p className={draft.autoPublish ? "sk-warn" : "sk-muted"} role="status" data-testid="doc-target-parent-warning">{warning}</p> : null}
      </label>
      <label className="admin-panel__field">
        <span>Knowledge source</span>
        <select className="admin-panel__input" value={draft.connectorKey} disabled={!editable}
          data-testid="doc-target-source" onChange={(event) => edit({ connectorKey: event.target.value })}>
          <option value="">Automatic: the source that covers the space</option>
          {sources.map((source) => <option key={source.key} value={source.key}>{source.key}</option>)}
          {unknownSource ? <option value={draft.connectorKey}>{`${draft.connectorKey} (no longer a Confluence source)`}</option> : null}
        </select>
        <span className="sk-muted">Syncs the published page into Knowledge. Add Confluence sources in Knowledge › Sources.</span>
        <FieldError text={shown.connectorKey} />
      </label>
    </div>
  );
}

function DocTargetActions({ busy, blocked, onDiscard, onSave }: { busy: boolean; blocked: boolean; onDiscard: () => void; onSave: () => void }) {
  return (
    <div className="sk-row">
      <button type="button" className="admin-panel__action-btn" disabled={busy}
        onClick={onDiscard}>Discard</button>
      <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="doc-target-save"
        disabled={busy || blocked} onClick={onSave}>
        {busy ? "Saving…" : "Save"}
      </button>
    </div>
  );
}
