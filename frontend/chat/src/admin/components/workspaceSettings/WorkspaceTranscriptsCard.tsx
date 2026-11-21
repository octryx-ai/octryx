import { useEffect, useState } from "react";

import { loadTranscriptSettings, saveTranscriptSettings } from "../../../chat/transcripts/transcriptApi";
import {
  RETENTION_MAX,
  RETENTION_MIN,
  readTranscriptSettings,
  retentionProblem,
  settingsChangeBody,
  settingsSaveErrors,
  type SettingsErrors,
  type TranscriptSettings,
  type TranscriptSettingsAnswer,
} from "../../../chat/transcripts/transcriptModel";
import "../../../chat/transcripts/transcripts.css";
import { ToggleRow } from "../settingsKit/SettingsKit";

// Workspace → Coding tools & devices → "Session transcripts": whether octryx-claude sessions upload
// their full Claude Code transcript, and how long it is kept. Off by default. Members read it; Workspace admins,
// owners and platform admins (the server's `can_edit`) change it. The switch saves at once, the days with Save.
export function WorkspaceTranscriptsCard({ projectId }: { projectId: string }) {
  const [answer, setAnswer] = useState<TranscriptSettingsAnswer | null>(null);
  const [days, setDays] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [errors, setErrors] = useState<SettingsErrors>({});
  const [saved, setSaved] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let current = true;
    setAnswer(null);
    setProblem(null);
    loadTranscriptSettings(projectId).then((payload) => {
      if (!current) return;
      const read = readTranscriptSettings(payload);
      if (!read) setProblem("The server's answer was not a transcript setting.");
      else { setAnswer(read); setDays(String(read.retentionDays)); }
    }).catch(() => {
      if (current) setProblem("The transcript setting could not be loaded.");
    });
    return () => { current = false; };
  }, [projectId]);

  if (problem) return <section className="admin-panel__card"><p className="sk-err" role="alert">{problem}</p></section>;
  if (!answer) return null;

  const dayCount = days.trim() === "" ? Number.NaN : Number(days);
  const localDaysProblem = days === String(answer.retentionDays) ? null : retentionProblem(dayCount);
  const daysChanged = days !== String(answer.retentionDays);
  const editable = answer.canEdit && !busy;

  const save = (draft: TranscriptSettings, done: string) =>
    saveTranscripts({ projectId, answer, setAnswer, setDays, setErrors, setSaved, setBusy }, draft, done);

  const daysError = localDaysProblem ?? errors.retentionDays ?? null;
  return (
    <section className="admin-panel__card" aria-label="Session transcripts" data-testid="workspace-transcripts">
      <div className="admin-panel__section-header"><span>Session transcripts</span></div>
      <ToggleRow
        title="Full session transcripts"
        on={answer.enabled}
        disabled={!editable}
        testId="transcripts-enabled"
        onChange={(next) => void save({ enabled: next, retentionDays: answer.retentionDays },
          next ? "On. Sessions started from now on upload their transcript." : "Off. Running sessions stop uploading within seconds.")}
        sub="Uploads the full Claude Code transcript of octryx-claude sessions in this Workspace, subagents and file contents included. Secrets are redacted. Only Workspace admins and the session's owner can read it."
      />
      {errors.enabled ? <p className="sk-err" role="alert">{errors.enabled}</p> : null}
      <RetentionField answer={answer} days={days} editable={editable} busy={busy} daysError={daysError} daysChanged={daysChanged}
        localDaysProblem={localDaysProblem} onDays={(value) => { setDays(value); setErrors({}); setSaved(null); }}
        onDiscard={() => { setDays(String(answer.retentionDays)); setErrors({}); }}
        onSave={() => void save({ enabled: answer.enabled, retentionDays: dayCount }, "Saved. Older transcripts are deleted at the next cleanup.")} />
      {daysError ? <p className="sk-err" role="alert" data-testid="transcripts-retention-error">{daysError}</p> : null}
      <TranscriptSource answer={answer} />
      {errors.general ? <p className="sk-err" role="alert">{errors.general}</p> : null}
      {saved ? <p className="admin-panel__success" role="status">{saved}</p> : null}
    </section>
  );
}

type SaveContext = {
  projectId: string;
  answer: TranscriptSettingsAnswer;
  setAnswer: (answer: TranscriptSettingsAnswer) => void;
  setDays: (days: string) => void;
  setErrors: (errors: SettingsErrors) => void;
  setSaved: (saved: string | null) => void;
  setBusy: (busy: boolean) => void;
};

// Saves only what differs from the stored setting; the server's answer replaces the shown one, a refusal is shown per field.
async function saveTranscripts(
  { projectId, answer, setAnswer, setDays, setErrors, setSaved, setBusy }: SaveContext,
  draft: TranscriptSettings,
  done: string,
) {
  const body = settingsChangeBody(answer, draft);
  if (!Object.keys(body).length) return;
  setBusy(true);
  setErrors({});
  setSaved(null);
  try {
    const result = await saveTranscriptSettings(projectId, body);
    const read = result.ok ? readTranscriptSettings(result.body) : null;
    if (read) {
      setAnswer(read);
      setDays(String(read.retentionDays));
      setSaved(done);
    } else {
      setErrors(result.ok ? { general: "Not saved: the server's answer was not a transcript setting." } : settingsSaveErrors(result.status, result.body));
    }
  } catch {
    setErrors({ general: "Not saved: the request did not reach the server." });
  } finally {
    setBusy(false);
  }
}

// Where the setting comes from, and that a reader cannot change it.
function TranscriptSource({ answer }: { answer: TranscriptSettingsAnswer }) {
  return (
    <p className="sk-muted" data-testid="transcripts-source">
      {answer.source === "default" ? "Default setting." : "Set for this Workspace."}
      {answer.canEdit ? "" : " Read-only: Workspace admins and owners can change it."}
    </p>
  );
}

// The retention in days with Discard and Save while it differs from the stored value.
function RetentionField({ answer, days, editable, busy, daysError, daysChanged, localDaysProblem, onDays, onDiscard, onSave }: {
  answer: TranscriptSettingsAnswer;
  days: string;
  editable: boolean;
  busy: boolean;
  daysError: string | null;
  daysChanged: boolean;
  localDaysProblem: string | null;
  onDays: (value: string) => void;
  onDiscard: () => void;
  onSave: () => void;
}) {
  return (
    <div className="transcripts-retention">
      <label className="admin-panel__field">
        <span>Keep for (days)</span>
        <input type="number" inputMode="numeric" min={RETENTION_MIN} max={RETENTION_MAX} step={1} value={days}
          disabled={!editable} aria-invalid={daysError ? true : undefined} aria-label="Keep for days"
          data-testid="transcripts-retention"
          onChange={(event) => onDays(event.target.value)} />
      </label>
      {answer.canEdit && daysChanged ? (
        <div className="sk-row">
          <button type="button" className="admin-panel__action-btn" disabled={busy}
            onClick={onDiscard}>Discard</button>
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="transcripts-save"
            disabled={busy || Boolean(localDaysProblem)}
            onClick={onSave}>
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      ) : null}
    </div>
  );
}
