import { useCallback, useEffect, useRef, useState } from "react";

import { compactThread, decideDeviceApproval, loadDeviceJobs, stopDeviceJob } from "./deviceJobsApi";
import { DEVICE_JOB_EVENT, type DeviceJobEventDetail } from "./deviceJobEvents";
import {
  applyJobEvent, clock, jobModelLabel, jobState, readJobs, restoresDeviceTarget, secondsLeft, WAITING_RUNNER,
} from "./deviceJobsModel";
import { contextUse, turnBlocks, turnView, type ContextUse } from "./deviceTurnView";
import { type DeviceJob, type JobApproval } from "./deviceJobTypes";
import { hasExecutionTarget, setExecutionTarget } from "./executionTarget";
import { ToolFoldView } from "../ToolStepFold";
import { foldDeviceToolSteps } from "../toolStepFoldModel";
import { EngineBadge } from "../engines/EngineBadge";
import { TranscriptLink } from "../transcripts/TranscriptButton";
import "./devices.css";

// The live device job of a thread: the job bar with Stop, the streamed text and tool cards,
// and the approval card with its countdown (only the owner can answer; no answer in time is a deny). The turn's
// final answer lands in the timeline as an ordinary assistant message.
function ApprovalCard({ job, approval, now, onDecided }: {
  job: DeviceJob;
  approval: JobApproval;
  now: number;
  onDecided: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const left = secondsLeft(approval.expiresAt, now);
  const decide = async (decision: "allow_once" | "allow_job_edits" | "deny") => {
    setBusy(true);
    try {
      await decideDeviceApproval(job.id, approval.id, decision);
      setProblem(null);
      onDecided();
    } catch (error) {
      const code = (error as { code?: unknown }).code;
      setProblem(code === "approval_expired" ? "Timed out → denied." : "The decision could not be sent.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="approval-inline">
      <div className="approval-inline__icon">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z" /></svg>
      </div>
      <div className="approval-inline__body">
        <div className="approval-inline__title">Approval needed on {job.deviceName}</div>
        <div className="approval-inline__meta">
          <span>{approval.tool}</span>
          <span>expires in {clock(left)}</span>
        </div>
        <div className="approval-inline__summary">
          Claude Code asks before this step on your device. Only you (the device owner) can answer; no answer in time
          = denied.
        </div>
        {approval.inputPreview ? <pre className="device-pre">{approval.inputPreview}</pre> : null}
        {problem ? <p className="work-area__error" role="alert">{problem}</p> : null}
      </div>
      <div className="approval-inline__actions device-approval-actions">
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--danger" disabled={busy || left === 0}
          onClick={() => void decide("deny")}>Deny</button>
        {approval.canAllowJobEdits ? (
          <button type="button" className="admin-panel__action-btn" disabled={busy || left === 0}
            title={`Allow file edits inside ${job.folder} until this job ends`}
            onClick={() => void decide("allow_job_edits")}>Allow edits for this job</button>
        ) : null}
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary"
          disabled={busy || left === 0} onClick={() => void decide("allow_once")}>Allow once</button>
      </div>
    </div>
  );
}

type ThreadMessages = { role?: string; model?: string | null }[] | null | undefined;

function useDeviceJobList(sessionId: string | null | undefined, messages: ThreadMessages) {
  const messagesRef = useRef(messages);
  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);
  const [jobs, setJobs] = useState<DeviceJob[]>([]);
  const [now, setNow] = useState(() => Date.now());
  const [stopProblem, setStopProblem] = useState<string | null>(null);

  const reload = useCallback(async () => {
    if (!sessionId) return;
    try {
      const listed = readJobs(await loadDeviceJobs(sessionId));
      if (!listed) return;
      setJobs(listed);
      const latest = listed[listed.length - 1];
      // Sticky per thread: opening a thread that still runs on a device keeps that target.
      if (latest && !hasExecutionTarget(sessionId) && restoresDeviceTarget(latest, messagesRef.current)) {
        setExecutionTarget(sessionId, { kind: "device", deviceId: latest.deviceId, folder: latest.folder,
          profile: latest.profile === "seat" ? "seat" : "governed", model: latest.requestedModel });
      }
    } catch {
      /* the thread simply shows no device job */
    }
  }, [sessionId]);

  useEffect(() => {
    setJobs([]);
    void reload();
  }, [reload]);

  useEffect(() => {
    const onEvent = (event: Event) => {
      const detail = (event as CustomEvent<DeviceJobEventDetail>).detail;
      if (!detail || detail.sessionId !== sessionId) return;
      setJobs((current) => {
        const next = applyJobEvent(current, detail.payload);
        if (next === null) {
          void reload();
          return current;
        }
        return next;
      });
    };
    window.addEventListener(DEVICE_JOB_EVENT, onEvent);
    return () => window.removeEventListener(DEVICE_JOB_EVENT, onEvent);
  }, [sessionId, reload]);
  return { jobs, now, setNow, stopProblem, setStopProblem, reload };
}

// The newest job, its turn and state; the clock ticks while it runs or an approval counts down.
function useNewestJob(jobs: DeviceJob[], setNow: (now: number) => void) {
  const job = jobs[jobs.length - 1];
  const view = job ? turnView(job) : null;
  const state = job && view ? jobState(job, view.finished) : null;
  const pending = job?.approvals.filter((approval) => approval.status === "pending") ?? [];

  useEffect(() => {
    if (!state?.live && pending.length === 0) return undefined;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [state?.live, pending.length, setNow]);
  return { job, view, state, pending };
}

type TurnItems = ReturnType<typeof turnView>["items"];

function JobStream({ items }: { items: TurnItems }) {
  return (
    <div className="tool-inline-list device-job__stream">
      {turnBlocks(items).map((block) => {
        if (block.kind === "text") return <div key={block.key} className="device-answer">{block.text}</div>;
        const fold = foldDeviceToolSteps(block.tools);
        return fold ? (
          <ToolFoldView key={block.key} fold={fold}>
            {block.tools.map((item) => (
              <div key={item.key} className="tool-inline">
                <div className="tool-inline__header">
                  <span className="tool-inline__title">
                    <span className="tool-inline__badge">{item.tool}</span>
                    <span className="device-mono">{item.preview}</span>
                  </span>
                  <span className={`tool-inline__status tool-inline__status--${item.status === "error" ? "error" : item.status === "done" ? "success" : "running"}`}>
                    {item.status === "running" ? "running" : item.status === "error" ? "failed" : "done"}
                  </span>
                </div>
                {item.output ? <pre className="device-pre">{item.output}</pre> : null}
              </div>
            ))}
          </ToolFoldView>
        ) : null;
      })}
    </div>
  );
}

function ContextMeter({ use, sessionId, live }: { use: ContextUse; sessionId: string; live: boolean }) {
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const compact = async () => {
    setBusy(true);
    try {
      await compactThread(sessionId);
      setProblem(null);
    } catch {
      setProblem("The context could not be compacted.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="device-context" data-testid="device-context">
      <span className="device-context__label">Context {use.percent}%</span>
      <span className="device-context__bar" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={use.percent}
        aria-label={`Context ${use.percent}% of ${Math.round(use.window / 1000)}k tokens`}>
        <span className="device-context__fill" style={{ width: `${use.percent}%` }} />
      </span>
      <span className="device-context__tokens">{Math.round(use.used / 1000)}k / {Math.round(use.window / 1000)}k</span>
      <button type="button" className="admin-panel__action-btn" disabled={busy || live}
        title="Summarise the conversation so far and continue with a smaller context" onClick={() => void compact()}>
        Compact
      </button>
      {problem ? <span className="work-area__error" role="alert">{problem}</span> : null}
    </div>
  );
}

export function DeviceJobPanel({ sessionId, projectId, messages }: {
  sessionId: string | null | undefined;
  /** The thread's Workspace: the job line offers the job's transcript when one is stored. */
  projectId?: string | null;
  /** The thread's messages: a thread whose newest answer came from the Server does not reopen on the device. */
  messages?: { role?: string; model?: string | null }[] | null;
}) {
  const { jobs, now, setNow, stopProblem, setStopProblem, reload } = useDeviceJobList(sessionId, messages);
  const { job, view, state, pending } = useNewestJob(jobs, setNow);

  if (!job || !view || !state) return null;
  const context = contextUse(job);
  if (!state.live && state.tone === "done" && pending.length === 0) {
    // A finished turn leaves the timeline its answer; the thread keeps its context meter.
    return context && sessionId ? <ContextMeter use={context} sessionId={sessionId} live={false} /> : null;
  }

  const stop = async () => {
    try {
      await stopDeviceJob(job.id);
      setStopProblem(null);
    } catch {
      setStopProblem("The job could not be stopped.");
    }
  };

  return (
    <section className="device-job" aria-label={`Job on ${job.deviceName}`} aria-live="polite">
      <div className="message-row__identity-line">
        {/* The engine is fixed per job (Claude Code or Codex), so the title names the device only. */}
        <span className="message-row__participant-title">Session on {job.deviceName || "the server runners"}</span>
        <EngineBadge engine={job.engine} />
        <span className="message-row__participant-support">
          {jobModelLabel(job)}{job.folder ? ` · ${job.folder}` : ""} · job {job.id}
        </span>
        <TranscriptLink projectId={projectId} filter={{ deviceJobId: job.id }} testId="device-job-transcript" />
      </div>
      <div className={`device-jobbar device-jobbar--${state.tone}`}>
        <span className="device-row">
          <span className={`device-dot ${state.live ? "device-dot--busy" : state.tone === "attention" ? "device-dot--wait" : "device-dot--off"}`} />
          <b>{state.label}</b>
        </span>
        {state.live ? (
          <span className="device-row">
            <button type="button" className="admin-panel__action-btn admin-panel__action-btn--danger"
              disabled={job.stopping} onClick={() => void stop()}>
              {job.status === WAITING_RUNNER ? "Cancel" : "Stop job"}
            </button>
          </span>
        ) : null}
      </div>
      {stopProblem ? <p className="work-area__error" role="alert">{stopProblem}</p> : null}
      {context && sessionId ? <ContextMeter use={context} sessionId={sessionId} live={state.live} /> : null}
      {view.items.length ? <JobStream items={view.items} /> : null}
      {pending.map((approval) => (
        <ApprovalCard key={approval.id} job={job} approval={approval} now={now} onDecided={() => void reload()} />
      ))}
    </section>
  );
}
