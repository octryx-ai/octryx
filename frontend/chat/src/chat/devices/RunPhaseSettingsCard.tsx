import { useCallback, useEffect, useState, type ReactNode } from "react";

import { loadDeviceRunsPolicy, saveDeviceRunsPolicy } from "./devicesApi";
import {
  MAX_BROWSER_PHASES,
  MIN_SOURCES_HIGH,
  MIN_SOURCES_LOW,
  browserPhaseProblem,
  browserPhasesPatch,
  checkAttemptsPatch,
  minSourcesValue,
  readRunPhaseSettings,
  researchMinSourcesPatch,
  researchPhasesPatch,
  runPhaseSaveError,
  type RunPhaseSettings,
} from "./runPhaseSettingsModel";
import "../../admin/components/settingsKit/settingsKit.css";
import "./devices.css";

// Workspace settings › Coding tools & devices › "Workflow runs on devices": the phases that get a browser of
// their own (`device_runs.browser_phases`), the research phases (`device_runs.research_phases`) and their minimum
// of sources (`device_runs.research_min_sources`). Each field saves on its own with a one-key patch. Code
// conventions come from the code style only (backend services/code_style).
export function RunPhaseSettingsCard({ projectId }: { projectId: string }) {
  const [settings, setSettings] = useState<RunPhaseSettings | null>(null);
  const [loadProblem, setLoadProblem] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setSettings(readRunPhaseSettings(await loadDeviceRunsPolicy(projectId)));
      setLoadProblem(null);
    } catch {
      setLoadProblem("The run settings could not be loaded.");
    }
  }, [projectId]);
  useEffect(() => { void load(); }, [load]);

  if (!settings) return loadProblem ? <p className="sk-err" role="alert">{loadProblem}</p> : null;
  const editable = settings.canEdit && settings.policyValid;
  /** Saves one patch; the answer is the whole section again. Throws the field's words on a refusal. */
  const save = async (patch: Record<string, unknown>) => {
    try {
      setSettings(readRunPhaseSettings(await saveDeviceRunsPolicy(projectId, patch)));
    } catch (error) {
      throw new Error(runPhaseSaveError(error));
    }
  };

  return (
    <section className="admin-panel__card" aria-label="Workflow runs on devices" data-testid="run-phase-settings">
      <div className="admin-panel__section-header"><span>Workflow runs on devices</span></div>
      {!editable ? <p className="sk-hint">Only the Workspace's admins and owners change these settings.</p> : null}
      <PhaseListField testId="browser-phases" label="Browser in phases" example="epic-delivery.implement"
        phases={settings.browserPhases} disabled={!editable}
        empty="No phase: only phases whose workflow asks for a browser get one."
        hint={<>These phases get a browser of their own in this Workspace's runs, as <code>workflow.phase</code>, for
          example <code>epic-delivery.implement</code>. The browser may only open localhost of your own app.</>}
        onSave={(phases) => save(browserPhasesPatch(phases))} />
      <PhaseListField testId="research-phases" label="Research phases" example="spec-writing.draft"
        phases={settings.researchPhases} disabled={!editable}
        empty="No phase: no phase has to research on the web."
        hint={<>These phases get <code>web_search</code> and <code>web_fetch</code>, must research before writing and
          cite their sources as URLs; two blocking checks (searches and distinct cited URLs).</>}
        onSave={(phases) => save(researchPhasesPatch(phases))} />
      <NumberField id="research-min-sources" label="Minimum sources" count={settings.researchMinSources}
        disabled={!editable} inEffect={settings.researchPhases.length > 0}
        hint={<>How many searches/fetches and distinct cited URLs a research phase needs.
          {settings.researchPhases.length > 0 ? null : " Not in effect: add a research phase first."}</>}
        saved="Saved. Research phases of runs started from now on need this many sources."
        onSave={(count) => save(researchMinSourcesPatch(count))} />
      <NumberField id="check-attempts" label="Attempts after failed checks" count={settings.checkAttempts}
        disabled={!editable} inEffect
        hint={<>How often a red gate, pipeline or CI result sends the work back to the agent. Then the run stops as
          <code> checks_failed</code> with the failed checks, and a person decides.</>}
        saved="Saved. Runs use this from their next failed check."
        onSave={(count) => save(checkAttemptsPatch(count))} />
    </section>
  );
}

/** A list of `workflow.phase` keys as removable chips plus an input; each change saves the whole list. */
function PhaseListField({ testId, label, example, hint, empty, phases, disabled, onSave }: {
  testId: string;
  label: string;
  example: string;
  hint: ReactNode;
  empty: string;
  phases: string[];
  disabled: boolean;
  onSave: (phases: string[]) => Promise<void>;
}) {
  const [draft, setDraft] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const store = async (next: string[]) => {
    setBusy(true);
    try {
      await onSave(next);
      setProblem(null);
      return true;
    } catch (error) {
      setProblem((error as Error).message);
      return false;
    } finally {
      setBusy(false);
    }
  };
  const add = async () => {
    const reason = browserPhaseProblem(draft, phases, example);
    if (reason) {
      setProblem(reason);
      return;
    }
    if (await store([...phases, draft.trim()])) setDraft("");
  };

  return (
    <div className="admin-panel__field" data-testid={testId}>
      <span>{label}</span>
      <p className="sk-hint">{hint}</p>
      <div className="sk-chips">
        {phases.map((phase) => (
          <span key={phase} className="admin-policy-chip admin-policy-chip--secondary sk-chip-removable">
            <span>{phase}</span>
            {!disabled ? (
              <button type="button" className="sk-chip-remove" aria-label={`Remove ${phase}`} disabled={busy}
                onClick={() => void store(phases.filter((item) => item !== phase))}>×</button>
            ) : null}
          </span>
        ))}
        {phases.length === 0 ? <span className="sk-muted">{empty}</span> : null}
      </div>
      {!disabled ? (
        <div className="sk-row">
          <input className="admin-users__toolbar-input" value={draft} placeholder={example}
            aria-label={`Add a phase to ${label}`} aria-invalid={problem ? true : undefined} data-testid={`${testId}-input`}
            disabled={busy || phases.length >= MAX_BROWSER_PHASES}
            onChange={(event) => { setDraft(event.target.value); setProblem(null); }}
            onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); void add(); } }} />
          <button type="button" className="admin-panel__action-btn" disabled={busy || !draft.trim()}
            data-testid={`${testId}-add`} onClick={() => void add()}>Add</button>
        </div>
      ) : null}
      {problem ? <p className="sk-err" role="alert">{problem}</p> : null}
    </div>
  );
}

/** A whole number 1..20 of the device_runs section (research_min_sources, check_attempts), saved on its own. */
function NumberField({ id, label, hint, saved, count, inEffect, disabled, onSave }: {
  id: string;
  label: string;
  hint: ReactNode;
  saved: string;
  count: number;
  inEffect: boolean;
  disabled: boolean;
  onSave: (count: number) => Promise<void>;
}) {
  const [draft, setDraft] = useState(String(count));
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setDraft(String(count)); }, [count]);
  const parsed = minSourcesValue(draft);
  const changed = draft.trim() !== String(count);
  const off = disabled || !inEffect;

  const submit = async () => {
    if ("problem" in parsed) {
      setMessage({ ok: false, text: parsed.problem });
      return;
    }
    setBusy(true);
    try {
      await onSave(parsed.value);
      setMessage({ ok: true, text: saved });
    } catch (error) {
      setMessage({ ok: false, text: (error as Error).message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="admin-panel__field" data-testid={id}>
      <label htmlFor={`${id}-input`}>{label}</label>
      <p className="sk-hint">{hint}</p>
      <div className="sk-row">
        <input id={`${id}-input`} className="admin-users__toolbar-input" type="number" inputMode="numeric"
          min={MIN_SOURCES_LOW} max={MIN_SOURCES_HIGH} step={1} value={draft} disabled={off || busy}
          aria-invalid={message && !message.ok ? true : undefined} data-testid={`${id}-input`}
          onChange={(event) => { setDraft(event.target.value); setMessage(null); }}
          onKeyDown={(event) => { if (event.key === "Enter" && changed) { event.preventDefault(); void submit(); } }} />
        {!disabled ? (
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary"
            data-testid={`${id}-save`} disabled={off || busy || !changed} onClick={() => void submit()}>
            {busy ? "Saving…" : "Save"}
          </button>
        ) : null}
      </div>
      {message ? <p className={message.ok ? "admin-panel__success" : "sk-err"} role={message.ok ? "status" : "alert"}>{message.text}</p> : null}
    </div>
  );
}
