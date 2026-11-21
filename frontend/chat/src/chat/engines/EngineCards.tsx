import { useEffect, useState } from "react";

import { OptionCards } from "../../admin/components/settingsKit/SettingsKit";
import "../../admin/components/settingsKit/settingsKit.css";
import {
  loadPlatformEngine, loadWorkspaceEngines, saveOwnEngine, savePlatformEngine, saveWorkspaceEngines, type SaveResult,
} from "./engineApi";
import {
  ENGINES, allowedProblem, effectiveLine, engineLabel, engineSaveErrors, notAllowedNotice, personalEngineBody,
  personalOptions, personalValue, platformDefaultHint, readPlatformEngine, readWorkspaceEngines, sameDraft,
  toggleAllowed, workspaceDefaultOptions, workspaceDraftOf, workspaceEnginesBody,
  type EngineErrors, type PlatformEngine, type WorkspaceDraft, type WorkspaceEngines,
} from "./engineModel";
import "./engines.css";
import { SEAT_CARD_LABEL, seatCardHref } from "../agents/agentsFocus";

// Coding engine: Claude Code or Codex. The platform admin sets the default, a Workspace's admins
// decide which engines are allowed there and the Workspace default, and each person chooses among the allowed ones.
// Every change is audited on the server.

const ENGINE_DESC: Record<string, string> = {
  claude_code: "Anthropic's coding agent.",
  codex: "OpenAI's coding agent, on the Workspace's company models through the gateway.",
};

type Saved = { text: string } | null;

/** Runs a save and turns its answer into the new state or the errors at their fields. */
async function runSave<T>(request: () => Promise<SaveResult>, read: (body: unknown) => T | null,
  scope: "platform" | "workspace" | "person"): Promise<{ value: T | null; errors: EngineErrors }> {
  try {
    const result = await request();
    const value = result.ok ? read(result.body) : null;
    if (value) return { value, errors: {} };
    return { value: null, errors: result.ok ? { general: "Not saved: the server's answer was not an engine setting." } : engineSaveErrors(result.status, result.body, scope) };
  } catch {
    return { value: null, errors: { general: "Not saved: the request did not reach the server." } };
  }
}

function Feedback({ errors, saved }: { errors: EngineErrors; saved: Saved }) {
  return (
    <>
      {errors.general ? <p className="sk-err" role="alert">{errors.general}</p> : null}
      {saved ? <p className="admin-panel__success" role="status">{saved.text}</p> : null}
    </>
  );
}

// ---- Platform -----------------------------------------------------------------------------------------------------

/** Admin › Models › Defaults › Coding engine: the platform default (platform admins). */
export function PlatformEngineCard() {
  const [answer, setAnswer] = useState<PlatformEngine | null>(null);
  const [draft, setDraft] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [errors, setErrors] = useState<EngineErrors>({});
  const [saved, setSaved] = useState<Saved>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let current = true;
    loadPlatformEngine().then((payload) => {
      if (!current) return;
      const read = readPlatformEngine(payload);
      if (read) { setAnswer(read); setDraft(read.default); } else setProblem("The server's answer was not an engine setting.");
    }).catch(() => { if (current) setProblem("The coding engine setting could not be loaded."); });
    return () => { current = false; };
  }, []);

  if (problem) return <section className="admin-panel__card"><p className="sk-err" role="alert">{problem}</p></section>;
  if (!answer) return null;

  const save = async () => {
    setBusy(true);
    setErrors({});
    setSaved(null);
    const result = await runSave(() => savePlatformEngine({ default: draft }), readPlatformEngine, "platform");
    if (result.value) {
      setAnswer(result.value);
      setDraft(result.value.default);
      setSaved({ text: `Saved. New sessions use ${engineLabel(result.value.default)} unless a Workspace or person chooses otherwise.` });
    } else setErrors(result.errors);
    setBusy(false);
  };

  return (
    <section className="admin-panel__card" aria-label="Coding engine" data-testid="platform-engine">
      <div className="admin-panel__section-header"><span>Coding engine</span></div>
      <p className="sk-hint">Default coding engine for new sessions. Workspaces can override this and limit which engines their members may use.</p>
      <OptionCards name="platform-engine" label="Default coding engine for new sessions" value={draft}
        disabled={!answer.canEdit || busy}
        options={answer.engines.map((engine) => ({ value: engine, title: engineLabel(engine), desc: ENGINE_DESC[engine] ?? "" }))}
        onChange={(next) => { setDraft(next); setErrors({}); setSaved(null); }} />
      {errors.default ? <p className="sk-err" role="alert" data-testid="platform-engine-error">{errors.default}</p> : null}
      {answer.canEdit ? null : <p className="sk-muted">Read-only: only platform admins can change it.</p>}
      {answer.canEdit && draft !== answer.default ? (
        <div className="sk-row sk-row--end">
          <button type="button" className="admin-panel__action-btn" disabled={busy} onClick={() => { setDraft(answer.default); setErrors({}); }}>Discard</button>
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" disabled={busy}
            data-testid="platform-engine-save" onClick={() => void save()}>{busy ? "Saving…" : "Save"}</button>
        </div>
      ) : null}
      <Feedback errors={errors} saved={saved} />
    </section>
  );
}

// ---- Workspace ----------------------------------------------------------------------------------------------------

function useWorkspaceEngines(projectId: string) {
  const [answer, setAnswer] = useState<WorkspaceEngines | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  useEffect(() => {
    let current = true;
    setAnswer(null);
    setProblem(null);
    if (!projectId) return () => { current = false; };
    loadWorkspaceEngines(projectId).then((payload) => {
      if (!current) return;
      const read = readWorkspaceEngines(payload);
      if (read) setAnswer(read); else setProblem("The server's answer was not an engine setting.");
    }).catch(() => { if (current) setProblem("The coding engine setting could not be loaded."); });
    return () => { current = false; };
  }, [projectId]);
  return { answer, setAnswer, problem };
}

/** The person's own choice among the Workspace's allowed engines (My settings › Profile). */
function PersonalEngineChoice({ projectId, answer, onSaved }: {
  projectId: string;
  answer: WorkspaceEngines;
  onSaved: (next: WorkspaceEngines) => void;
}) {
  const [errors, setErrors] = useState<EngineErrors>({});
  const [saved, setSaved] = useState<Saved>(null);
  const [busy, setBusy] = useState(false);
  const notice = notAllowedNotice(answer.effective);

  const choose = async (value: string) => {
    setBusy(true);
    setErrors({});
    setSaved(null);
    const result = await runSave(() => saveOwnEngine(projectId, personalEngineBody(value)), readWorkspaceEngines, "person");
    if (result.value) {
      onSaved(result.value);
      setSaved({ text: `Saved. Your next session uses ${engineLabel(result.value.effective.engine)}.` });
    } else setErrors(result.errors);
    setBusy(false);
  };

  return (
    <div className="engine-personal" data-testid="engine-personal">
      {notice ? <p className="engine-notice" role="status" data-testid="engine-not-allowed">{notice}</p> : null}
      <OptionCards name={`engine-me-${projectId}`} label="Your coding engine" value={personalValue(answer.effective)} disabled={busy}
        options={personalOptions(answer.effective, answer.engines).map((option) => ({
          value: option.value,
          title: option.label,
          desc: option.hint ?? (option.value ? ENGINE_DESC[option.value] ?? "" : "Follows the Workspace's setting."),
          disabled: option.disabled,
        }))}
        onChange={(next) => void choose(next)} />
      {errors.engine ? <p className="sk-err" role="alert" data-testid="engine-personal-error">{errors.engine}</p> : null}
      <Feedback errors={errors} saved={saved} />
    </div>
  );
}

/** My settings › Profile › Your coding engine: per Workspace in focus. */
export function PersonalEngineCard({ projectId, workspaceName }: { projectId: string; workspaceName: string }) {
  const { answer, setAnswer, problem } = useWorkspaceEngines(projectId);
  const where = workspaceName ? ` in ${workspaceName}` : " in this Workspace";
  return (
    <section className="admin-panel__card" aria-label="Your coding engine" data-testid="personal-engine">
      <div className="admin-panel__section-header"><span>Your coding engine</span></div>
      {!projectId ? <p className="sk-hint">Choose a Workspace in the switch at the top to set your coding engine there.</p> : null}
      {problem ? <p className="sk-err" role="alert">{problem}</p> : null}
      {answer ? (
        <>
          <p className="sk-hint">What your coding sessions run on{where}. You can choose among the engines this Workspace allows.</p>
          <PersonalEngineChoice projectId={projectId} answer={answer} onSaved={setAnswer} />
          <p className="sk-muted" data-testid="engine-effective">{effectiveLine(answer.effective)}</p>
        </>
      ) : null}
    </section>
  );
}

/** Workspace settings › Coding tools & devices › Coding engine: allowed engines and the Workspace default. */
export function WorkspaceEngineCard({ projectId }: { projectId: string }) {
  const { answer, setAnswer, problem } = useWorkspaceEngines(projectId);
  const [draft, setDraft] = useState<WorkspaceDraft | null>(null);
  const [errors, setErrors] = useState<EngineErrors>({});
  const [saved, setSaved] = useState<Saved>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { setDraft(answer ? workspaceDraftOf(answer) : null); }, [answer]);

  if (problem) return <section className="admin-panel__card"><p className="sk-err" role="alert">{problem}</p></section>;
  if (!answer || !draft) return null;

  const editable = answer.canEdit && !busy;
  const changed = !sameDraft(draft, workspaceDraftOf(answer));
  const allowedError = allowedProblem(draft.allowed) ?? errors.allowed ?? null;
  const hint = platformDefaultHint(draft.allowed, answer.effective.platformDefault, answer.engines);
  const edit = (next: WorkspaceDraft) => { setDraft(next); setErrors({}); setSaved(null); };

  const save = async () => {
    setBusy(true);
    setErrors({});
    setSaved(null);
    const result = await runSave(() => saveWorkspaceEngines(projectId, workspaceEnginesBody(draft)), readWorkspaceEngines, "workspace");
    if (result.value) {
      setAnswer(result.value);
      setSaved({ text: "Saved. New sessions in this Workspace follow it; running sessions keep their engine." });
    } else setErrors(result.errors);
    setBusy(false);
  };

  return (
    <section className="admin-panel__card" aria-label="Coding engine" data-testid="workspace-engines">
      <div className="admin-panel__section-header"><span>Coding engine</span></div>
      <p className="sk-hint">Which coding engines members may use in this Workspace, and the one they get without a choice of their own.</p>
      <fieldset className="engine-allowed" disabled={!editable}>
        <legend>Allowed engines</legend>
        {(answer.engines.length ? answer.engines : ENGINES).map((engine) => (
          <label key={engine} className="admin-panel__checkbox">
            <input type="checkbox" checked={draft.allowed.includes(engine)} data-testid={`engine-allow-${engine}`}
              aria-invalid={allowedError ? true : undefined}
              onChange={(event) => edit(toggleAllowed(draft, engine, event.target.checked, answer.engines))} />
            {engineLabel(engine)}
          </label>
        ))}
      </fieldset>
      {allowedError ? <p className="sk-err" role="alert" data-testid="engine-allowed-error">{allowedError}</p> : null}
      <label className="admin-panel__field engine-default">
        <span>Default for this Workspace</span>
        <select className="admin-panel__input" value={draft.default} disabled={!editable} data-testid="engine-default"
          aria-invalid={errors.default ? true : undefined}
          onChange={(event) => edit({ ...draft, default: event.target.value })}>
          {workspaceDefaultOptions(draft.allowed, answer.effective.platformDefault, answer.engines).map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </select>
      </label>
      {hint && !draft.default ? <p className="sk-muted">{hint}</p> : null}
      {errors.default ? <p className="sk-err" role="alert" data-testid="engine-default-error">{errors.default}</p> : null}
      {answer.canEdit && changed ? (
        <div className="sk-row sk-row--end">
          <button type="button" className="admin-panel__action-btn" disabled={busy} onClick={() => edit(workspaceDraftOf(answer))}>Discard</button>
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="engine-save"
            disabled={busy || Boolean(allowedProblem(draft.allowed))} onClick={() => void save()}>
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      ) : null}
      <Feedback errors={errors} saved={saved} />
      <p className="sk-muted" data-testid="engine-codex-seat-pointer">Codex with your own ChatGPT subscription has its own switch under{" "}
        <a className="sk-link" href={seatCardHref(projectId)} data-testid="engine-codex-seat-link">Agents › {SEAT_CARD_LABEL}</a>.</p>
      <p className="sk-muted" data-testid="engine-workspace-source">
        {effectiveLine(answer.effective)}. {answer.source === "default" ? "Default setting." : "Set for this Workspace."}
        {answer.canEdit ? "" : " Read-only: Workspace admins and owners can change it; choose your own under My settings › Profile."}
      </p>
    </section>
  );
}
