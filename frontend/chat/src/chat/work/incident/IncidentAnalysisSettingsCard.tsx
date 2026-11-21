import { useEffect, useState } from "react";

import { loadAnalysisSettings, saveAnalysisSettings } from "./incidentApi";
import {
  MAX_OUTPUT_TOKENS_MAX,
  MAX_OUTPUT_TOKENS_MIN,
  analysisSettingsError,
  analysisSettingsPayload,
  intakeErrorText,
  readAnalysisSettings,
} from "./incidentSettingsModel";
import type { AnalysisRunner, AnalysisSettings } from "./incidentSettingsModel";

type Message = { ok: boolean; text: string };

const SUBJECT = "the incident analysis settings";

const RUNNERS: { value: AnalysisRunner; label: string }[] = [
  { value: "governed", label: "Governed (platform models, this Workspace's model policy)" },
  {
    value: "seat",
    label: "Seat (each user's own Claude subscription: run `octryx-claude analyze <KEY>`; the server never starts analyses, automatic analysis is off)",
  },
];

// Automatic incident analysis and Jira questions to the reporter for one Workspace (B/D). Both are opt-in:
// auto-analysis is off by default (at most one per item per 24 h, never for closed items), and questions are only
// posted where the Jira workflow writes back (execute mode and its mapping). The runner says who runs an analysis: the
// server (governed) or each user in their own seat session; with `seat` the server never starts one.
export function IncidentAnalysisSettingsCard({ projectId }: { projectId: string }) {
  const [settings, setSettings] = useState<AnalysisSettings | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<Message | null>(null);

  useEffect(() => {
    let current = true;
    setSettings(null); setProblem(null); setMessage(null);
    loadAnalysisSettings(projectId).then((payload) => {
      if (!current) return;
      const read = readAnalysisSettings(payload);
      if (read) setSettings(read);
      else setProblem("The server's answer was not the analysis settings.");
    }).catch((error) => { if (current) setProblem(intakeErrorText(error, "load the analysis settings", SUBJECT)); });
    return () => { current = false; };
  }, [projectId]);

  if (problem) return <p className="work-area__error" role="alert" data-testid="analysis-settings-error">{problem}</p>;
  if (!settings) return <p className="work-detail__empty" role="status">Loading the analysis settings…</p>;

  const error = analysisSettingsError(settings);
  const update = (patch: Partial<AnalysisSettings>) => { setSettings({ ...settings, ...patch }); setMessage(null); };
  // The save button is disabled while the settings are invalid.
  const save = async () => {
    setBusy(true);
    setMessage(null);
    try {
      await saveAnalysisSettings(projectId, analysisSettingsPayload(settings));
      setMessage({ ok: true, text: "Saved the analysis settings." });
    } catch (failure) {
      setMessage({ ok: false, text: intakeErrorText(failure, "save the analysis settings", SUBJECT) });
    } finally {
      setBusy(false);
    }
  };
  const readOnly = !settings.canEdit;
  const seat = settings.runner === "seat";

  return (
    <section className="work-config__section incident-settings" aria-label="Incident analysis" data-testid="analysis-settings">
      <header className="work-config__header">
        <div>
          <div className="work-area__eyebrow">Incident analysis</div>
          <h2>Automatic analysis and reporter questions</h2>
        </div>
      </header>
      <p className="work-detail__empty">
        An analysis runs through the governed model route with this Workspace's model policy and data classification
        {settings.maxCostUsd !== null ? `, capped at $${settings.maxCostUsd.toFixed(2)} per run` : ""}. It is written as a
        note by an agent and never changes an item by itself.
      </p>
      <fieldset className="work-detail__stack" disabled={readOnly} data-testid="analysis-runner">
        <legend className="work-area__eyebrow">Runner</legend>
        {RUNNERS.map((runner) => (
          <label key={runner.value} className="incident-settings__row">
            <input type="radio" name="analysis-runner" value={runner.value} checked={settings.runner === runner.value}
              data-testid={`analysis-runner-${runner.value}`} onChange={() => update({ runner: runner.value })} />
            {runner.label}
          </label>
        ))}
      </fieldset>
      <label className="incident-settings__row">
        Max output tokens per request
        <input value={settings.maxOutputTokens} disabled={readOnly} inputMode="numeric" aria-label="Max output tokens per request"
          data-testid="analysis-max-output-tokens" onChange={(event) => update({ maxOutputTokens: event.target.value })} />
        <span>({MAX_OUTPUT_TOKENS_MIN}–{MAX_OUTPUT_TOKENS_MAX})</span>
      </label>
      {seat ? (
        <p className="work-area__notice" role="note" data-testid="analysis-settings-seat">
          Seat runner: automatic analysis does not run (the server ignores the options below until the runner is
          Governed). Each user runs <code>octryx-claude analyze &lt;KEY&gt;</code> in their own seat session.
        </p>
      ) : null}
      {!settings.modelPolicy && !seat ? (
        <p className="work-area__notice" role="note" data-testid="analysis-settings-no-policy">
          No model policy is set for the analysis in this Workspace: every analysis needs configuration until a
          Workspace admin sets one. There is no implicit model.
        </p>
      ) : null}
      <label className="incident-settings__row">
        <input type="checkbox" checked={settings.servicenowNewIncidents} disabled={readOnly} data-testid="auto-servicenow"
          onChange={(event) => update({ servicenowNewIncidents: event.target.checked })} />
        Analyse new ServiceNow incidents automatically (at most once per item in 24 hours; never closed items)
        {seat ? " (not with the Seat runner)" : ""}
      </label>
      <div className="incident-settings__row">
        <label className="incident-settings__row">
          <input type="checkbox" checked={settings.jiraLabelOn} disabled={readOnly} data-testid="auto-jira"
            onChange={(event) => update({ jiraLabelOn: event.target.checked })} />
          Analyse Jira items with the label{seat ? " (not with the Seat runner)" : ""}
        </label>
        <input value={settings.jiraLabel} disabled={readOnly || !settings.jiraLabelOn} aria-label="Jira label" data-testid="auto-jira-label"
          onChange={(event) => update({ jiraLabel: event.target.value })} />
      </div>
      <label className="incident-settings__row">
        <input type="checkbox" checked={settings.askReporter} disabled={readOnly} data-testid="ask-reporter"
          onChange={(event) => update({ askReporter: event.target.checked })} />
        Ask the Jira reporter the analysis' open questions as a comment (once per analysis; only where the Jira workflow
        writes back)
      </label>
      {error ? <p className="work-area__error" role="alert" data-testid="analysis-settings-invalid">{error}</p> : null}
      {readOnly ? <p className="work-detail__empty" data-testid="analysis-settings-readonly">Read-only: Workspace admins and owners change these settings.</p> : (
        <div>
          <button type="button" className="work-area__button is-active" disabled={busy || Boolean(error)} onClick={() => void save()}
            data-testid="analysis-settings-save">
            {busy ? "Saving…" : "Save analysis settings"}
          </button>
        </div>
      )}
      {message ? <p className={message.ok ? "work-area__notice" : "work-area__error"} role={message.ok ? "status" : "alert"} data-testid="analysis-settings-message">{message.text}</p> : null}
    </section>
  );
}
