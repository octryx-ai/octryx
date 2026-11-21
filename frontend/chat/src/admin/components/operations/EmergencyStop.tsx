import { useEffect, useId, useState } from "react";

import { DataTable, type DataTableColumn } from "../../../layout/DataTable";
import { EmptyLine } from "../../../layout/EmptyLine";
import { SidePanel } from "../../../layout/SidePanel";
import { TimeText } from "../../utils/TimeText";
import { useConfirmAction, type ConfirmRequest } from "../confirm/useConfirmAction";
import {
  heldText,
  holdByText,
  PLATFORM_HOLD_TEXT,
  resumeOffer,
  resumeRefusalText,
  resumeResultText,
  type Hold,
} from "../securityControls/securityControlsModel";
import { emergencyStop, loadNewStartsHeld, loadStopHistory, loadStopPreview, resumeNewStarts } from "./operationsApi";
import { previewSentence, stopCountText, type StopPreview, type StopPreviewJob, type StopPreviewRun, type StopRecord } from "./operationsEmergencyStop";

// Emergency stop: an explicit admin action with a required reason. The panel lists
// exactly what the stop touches (the server's preview), says that runs pause and can be continued, and shows the
// server's refusal verbatim. Nothing triggers it automatically.

const RUN_COLUMNS: DataTableColumn<StopPreviewRun>[] = [
  { key: "title", header: "Run", grow: true, render: (run) => run.title },
  { key: "workspace", header: "Workspace", nowrap: true, render: (run) => run.workspace },
];
const JOB_COLUMNS: DataTableColumn<StopPreviewJob>[] = [
  { key: "folder", header: "Folder", grow: true, render: (job) => job.folder || "Device job" },
  { key: "workspace", header: "Workspace", nowrap: true, render: (job) => job.workspace },
];

const message = (error: unknown, fallback: string) => (error instanceof Error && error.message ? error.message : fallback);

export function EmergencyStopPanel({ label, workspaceId, onClose, onStopped }: {
  label: string; workspaceId: string; onClose: () => void; onStopped: (result: string) => void;
}) {
  const [preview, setPreview] = useState<StopPreview | null>(null);
  const [loadError, setLoadError] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // A platform stop holds every Workspace: it needs its own, explicit confirmation beyond the reason.
  const platform = !workspaceId;
  const [platformConfirmed, setPlatformConfirmed] = useState(false);
  const reasonId = useId();

  useEffect(() => {
    let current = true;
    loadStopPreview(workspaceId).then(
      (next) => { if (current) setPreview(next); },
      (failure) => { if (current) setLoadError(message(failure, "What would stop could not be loaded.")); },
    );
    return () => { current = false; };
  }, [workspaceId]);

  const stop = async () => {
    setBusy(true);
    setError("");
    try {
      onStopped(await emergencyStop(workspaceId, reason));
    } catch (failure) {
      setError(message(failure, "The stop failed."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <SidePanel title={`${label}?`} subtitle={workspaceId ? "Emergency stop for this Workspace" : "Emergency stop for every Workspace"}
      onClose={() => { if (!busy) onClose(); }} testId="ops-stop-panel"
      footer={(
        <StopPanelFooter busy={busy} disabled={busy || !reason.trim() || (!preview && !loadError) || (platform && !platformConfirmed)}
          platform={platform} onClose={onClose} onStop={() => void stop()} />
      )}>
      <div className="ops-stop">
        <p className="ops-stop__lead">
          Running runs pause and their device jobs stop now. A paused run keeps its work and can be continued from its
          own page; runs waiting for a person are left alone.
        </p>
        {platform ? <PlatformStopWarning busy={busy} confirmed={platformConfirmed} onConfirmed={setPlatformConfirmed} /> : null}
        <StopPreviewParts preview={preview} loadError={loadError} />
        <label className="ops-stop__field" htmlFor={reasonId}>
          <span>Reason (required)</span>
          <textarea id={reasonId} className="ds-input ops-stop__reason" rows={3} value={reason} data-testid="ops-stop-reason"
            placeholder="Why you stop everything; it goes into the audit log." onChange={(event) => setReason(event.target.value)} />
        </label>
        {error ? <p className="ops-notice ops-notice--problem" role="alert" data-testid="ops-stop-error">{error}</p> : null}
      </div>
    </SidePanel>
  );
}

function StopPanelFooter({ busy, disabled, platform, onClose, onStop }: {
  busy: boolean; disabled: boolean; platform: boolean; onClose: () => void; onStop: () => void;
}) {
  return (
    <>
      <button type="button" className="ds-btn" disabled={busy} onClick={onClose}>Cancel</button>
      <button type="button" className="ds-btn ds-btn--danger" data-testid="ops-stop-confirm"
        disabled={disabled}
        onClick={onStop}>
        {busy ? "Stopping…" : platform ? "Stop the whole platform" : "Stop everything"}
      </button>
    </>
  );
}

// A platform stop holds every Workspace: its own, explicit confirmation beyond the reason.
function PlatformStopWarning({ busy, confirmed, onConfirmed }: { busy: boolean; confirmed: boolean; onConfirmed: (next: boolean) => void }) {
  return (
    <div className="ops-notice ops-notice--problem" data-testid="ops-stop-platform-warning">
      <p>
        <strong>This stops every Workspace on the platform</strong>, not just one: their running runs pause and
        no Workspace starts anything new until an admin resumes.
      </p>
      <label className="admin-panel__checkbox">
        <input type="checkbox" data-testid="ops-stop-platform-confirm" checked={confirmed}
          disabled={busy} onChange={(event) => onConfirmed(event.target.checked)} />
        <span>Yes, stop the whole platform</span>
      </label>
    </div>
  );
}

// What the stop touches as the server previews it: the sum, the runs that pause and the device jobs that stop.
function StopPreviewParts({ preview, loadError }: { preview: StopPreview | null; loadError: string }) {
  return (
    <>
      {loadError ? <p className="ops-notice ops-notice--problem" role="alert">{loadError}</p> : null}
      {preview ? <p className="ops-stop__sum" data-testid="ops-stop-sum">{previewSentence(preview)}</p> : null}
      {preview?.runs.length ? (
        <section className="ops-stop__part" aria-label="Runs that pause">
          <h3 className="ops-stop__title">Runs that pause</h3>
          <DataTable<StopPreviewRun> label="Runs that pause" testId="ops-stop-runs" rows={preview.runs} rowKey={(run) => run.id}
            columns={RUN_COLUMNS} />
        </section>
      ) : null}
      {preview?.jobs.length ? (
        <section className="ops-stop__part" aria-label="Device jobs that stop">
          <h3 className="ops-stop__title">Device jobs that stop</h3>
          <DataTable<StopPreviewJob> label="Device jobs that stop" testId="ops-stop-jobs" rows={preview.jobs} rowKey={(job) => job.id}
            columns={JOB_COLUMNS} />
        </section>
      ) : null}
      {!preview && !loadError ? <p className="ops-muted">Loading what would stop…</p> : null}
    </>
  );
}

/** The last emergency stops of this scope, folded under the page; read when it is opened. */
export function StopHistory({ workspaceId, reloadKey }: { workspaceId: string; reloadKey: number }) {
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState<StopRecord[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return undefined;
    let current = true;
    setError("");
    loadStopHistory(workspaceId).then(
      (next) => { if (current) setRows(next); },
      (failure) => { if (current) setError(message(failure, "The stops could not be loaded.")); },
    );
    return () => { current = false; };
  }, [open, workspaceId, reloadKey]);

  return (
    <details className="ops-history" data-testid="ops-history" onToggle={(event) => setOpen((event.target as HTMLDetailsElement).open)}>
      <summary className="ops-history__summary">Emergency stops</summary>
      <div className="ops-history__body">
        {error ? <EmptyLine text={error} testId="ops-history-error" /> : (
          <DataTable<StopRecord> label="Emergency stops" testId="ops-history-table" loading={open && rows === null}
            loadingLabel="the emergency stops" rows={rows ?? []} rowKey={(row) => row.id}
            empty={{ text: "No emergency stop yet." }}
            columns={[
              { key: "at", header: "When", nowrap: true, render: (row) => <TimeText value={row.at} mode="recent" /> },
              { key: "by", header: "Who", nowrap: true, render: (row) => row.by },
              { key: "reason", header: "Reason", grow: true, clip: "28rem", render: (row) => <span title={row.reason}>{row.reason}</span> },
              { key: "count", header: "Stopped", nowrap: true, align: "end", render: (row) => stopCountText(row) },
            ]} />
        )}
      </div>
    </details>
  );
}

/**
 * While a stop holds new starts in this scope: says so and offers Resume to whoever may stop it (the caller
 * renders this only for them). It names who stopped, when and why. Resume lifts exactly this scope after an
 * in-page confirmation with a required reason; its result or refusal is shown in words. Under a platform stop a
 * Workspace view offers no Workspace resume (it would answer 409): platform admins switch to the platform view.
 * Paused runs are not continued by it.
 */
export function HeldStarts({ workspaceId, workspaceName, reloadKey, isPlatformAdmin, onShowPlatform, onResumed }: {
  workspaceId: string; workspaceName: string; reloadKey: number; isPlatformAdmin: boolean;
  onShowPlatform: () => void; onResumed: (result: string) => void;
}) {
  const [held, setHeld] = useState(false);
  const [hold, setHold] = useState<Hold | null>(null);
  const [checked, setChecked] = useState(0);
  const confirm = useConfirmAction();

  useEffect(() => {
    let current = true;
    loadNewStartsHeld(workspaceId).then(
      (next) => { if (current) { setHeld(next.held); setHold(next.hold); } },
      () => { if (current) { setHeld(false); setHold(null); } },
    );
    return () => { current = false; };
  }, [workspaceId, reloadKey, checked]);

  if (!held) return confirm.dialog;
  const where = workspaceName ? `in ${workspaceName}` : "on the whole platform";
  const offer = resumeOffer(hold, workspaceId, isPlatformAdmin);
  return (
    <>
      <div className="ops-held" role="status" data-testid="ops-held">
        <HoldFacts hold={hold} workspaceId={workspaceId} workspaceName={workspaceName} />
        {offer === "platform" ? (
          <button type="button" className="ds-btn ds-btn--sm" data-testid="ops-show-platform" onClick={onShowPlatform}>
            Open the platform view
          </button>
        ) : null}
        {offer === "resume" ? <button type="button" className="ds-btn ds-btn--sm" data-testid="ops-resume" onClick={() => confirm.ask(
          resumeConfirmation(where, workspaceId, workspaceName, onResumed, () => setChecked((n) => n + 1)))}>Resume…</button> : null}
      </div>
      {confirm.dialog}
    </>
  );
}

// Who stopped new starts in this scope, when and why, and the platform note under a platform stop.
function HoldFacts({ hold, workspaceId, workspaceName }: { hold: Hold | null; workspaceId: string; workspaceName: string }) {
  return (
    <div className="ops-held__body">
      <p className="ops-held__text"><strong>New starts are held.</strong> {heldText(hold?.scope === "platform" ? "" : workspaceName)}</p>
      {hold ? (
        <p className="ops-held__who" data-testid="ops-held-who">
          {holdByText(hold, workspaceName)}
          {hold.at ? <>, <TimeText value={hold.at} mode="recent" /></> : null}
          {hold.reason ? <>: <span className="ops-held__reason">{hold.reason}</span></> : "."}
        </p>
      ) : null}
      {hold?.scope === "platform" && workspaceId ? (
        <p className="ops-held__who" data-testid="ops-held-platform">{PLATFORM_HOLD_TEXT}</p>
      ) : null}
    </div>
  );
}

// The in-page confirmation of Resume: a required reason, then the resume; a refusal is said in words.
function resumeConfirmation(where: string, workspaceId: string, workspaceName: string, onResumed: (result: string) => void,
  onDone: () => void): ConfirmRequest {
  return {
    title: `Resume new starts ${where}?`,
    body: <p className="ops-confirm">Schedules and webhook Actions may start runs again. Runs the stop
      paused stay paused; continue each from its own page.</p>,
    confirmLabel: "Resume new starts",
    tone: "neutral",
    field: { label: "Reason", placeholder: "Why new starts may run again; it goes into the audit log.", required: true },
    run: async (reason) => {
      let result: unknown;
      try {
        result = await resumeNewStarts(workspaceId, reason);
      } catch (failure) {
        throw new Error(resumeRefusalText(failure));
      }
      onResumed(resumeResultText(result, workspaceName));
      onDone();
    },
    done: "",
  };
}
