import { useCallback, useEffect, useRef, useState } from "react";
import { formatExactTime, formatRelative } from "../../admin/utils/dateTime";
import { ACTIVE_WORKSPACE_EVENT, readStoredWorkspacePreference, readUrlWorkspaceId } from "../activeWorkspace";
import { SegmentedTabs } from "../../layout/SegmentedTabs";
import { DataTable, type DataTableColumn } from "../../layout/DataTable";
import { StatusLabel, type StatusTone } from "../../layout/StatusLabel";
import { loadJobs } from "./companionApi";
import { CompanionJobDetail, type WatchJob } from "./CompanionJobDetail";
import { JOBS_EMPTY, jobStateLabel, jobTitle, phaseText, targetText, type Job, type JobScope } from "./companionJobModel";

// The panel's job list: "Mine" (the person's runs) or "Team" (the runs of the active Workspace, following the
// global switch), as a compact table, not cards. A row opens the job's read-only detail inside the panel.

const SCOPES: { key: JobScope; label: string }[] = [{ key: "mine", label: "Mine" }, { key: "team", label: "Team" }];
const STATE_TONE: Record<Job["state"], StatusTone> = { working: "info", needs_you: "attention", problem: "problem", done: "neutral" };

// Two columns, so the job keeps its name in the narrow panel: the job (title; phase, where it runs when not on the
// server, owner and when, on a second line) and its state.
function jobColumns(scope: JobScope, now: () => number): DataTableColumn<Job>[] {
  return [
    { key: "job", header: "Job", grow: true, render: (job) => {
      // The separator only between parts that are there: a job without a phase on the server starts with its time,
      // not with "· 23 h ago".
      const meta = [phaseText(job), job.target?.kind === "server" ? "" : targetText(job.target), scope === "team" ? job.owner?.name : ""]
        .filter(Boolean).join(" · ");
      return (
        <span className="octryx-jobs__cell" data-testid="octryx-job-cell">
          <span className="octryx-jobs__title" title={jobTitle(job)}>{jobTitle(job)}</span>
          <span className="octryx-panel__meta octryx-jobs__meta">
            {meta}
            {job.since ? <>{meta ? " · " : ""}
              <time title={formatExactTime(job.since)}>{formatRelative(job.since, "", now())}</time></> : null}
          </span>
        </span>
      );
    } },
    { key: "state", header: "State", width: "10.5rem",
      render: (job) => <StatusLabel label={jobStateLabel(job)} tone={STATE_TONE[job.state]} /> },
  ];
}

function activeWorkspaceId(): string {
  return readUrlWorkspaceId() || readStoredWorkspacePreference() || "";
}

function useActiveWorkspaceId(): string {
  const [workspaceId, setWorkspaceId] = useState(activeWorkspaceId);
  useEffect(() => {
    const onChange = (event: Event) => setWorkspaceId((event as CustomEvent<string>).detail || "");
    const onPopState = () => setWorkspaceId(activeWorkspaceId());
    window.addEventListener(ACTIVE_WORKSPACE_EVENT, onChange);
    window.addEventListener("popstate", onPopState);
    return () => {
      window.removeEventListener(ACTIVE_WORKSPACE_EVENT, onChange);
      window.removeEventListener("popstate", onPopState);
    };
  }, []);
  return workspaceId;
}

export function CompanionJobs({ watchJob, isAdmin = false, pollMs = 30_000, now = Date.now }: {
  watchJob: WatchJob; isAdmin?: boolean; pollMs?: number; now?: () => number;
}) {
  const [scope, setScope] = useState<JobScope>("mine");
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [openRun, setOpenRun] = useState<string | null>(null);
  const workspaceId = useActiveWorkspaceId();
  const generation = useRef(0);

  const reload = useCallback(() => {
    const run = ++generation.current;
    loadJobs(scope, workspaceId).then((next) => {
      if (run !== generation.current) return;
      setProblem(null);
      setJobs(next);
    }).catch(() => {
      if (run === generation.current) setProblem("Jobs could not be loaded.");
    });
  }, [scope, workspaceId]);

  useEffect(() => {
    const loads = generation;
    setJobs(null);
    reload();
    const timer = setInterval(reload, pollMs);
    return () => {
      loads.current++;
      clearInterval(timer);
    };
  }, [pollMs, reload]);

  if (openRun) {
    return <CompanionJobDetail runId={openRun} watchJob={watchJob} isAdmin={isAdmin} now={now} onBack={() => { setOpenRun(null); reload(); }} />;
  }
  const empty = scope === "team" && !workspaceId ? "No run of your Workspaces worked in the last 24 hours." : JOBS_EMPTY[scope];
  return (
    <section className="octryx-panel__section" aria-label="Jobs" data-testid="octryx-jobs">
      <SegmentedTabs tabs={SCOPES} value={scope} onChange={(key) => setScope(key as JobScope)} label="Whose jobs"
        idPrefix="octryx-jobs" size="small" testId="octryx-jobs-scope" />
      {jobs?.length ? <p className="octryx-panel__hint" data-testid="octryx-jobs-window">Runs that worked in the last 24 hours.</p> : null}
      {problem ? (
        <div role="status" data-testid="octryx-jobs-problem">
          <p className="octryx-panel__hint">{problem}</p>
          <button type="button" className="admin-panel__action-btn" onClick={reload}>Try again</button>
        </div>
      ) : null}
      {!jobs && !problem ? <p className="octryx-panel__hint" role="status">Loading jobs…</p> : null}
      {jobs && !jobs.length ? <p className="octryx-panel__hint" data-testid="octryx-jobs-empty">{empty}</p> : null}
      {jobs?.length ? (
        <DataTable label="Jobs" columns={jobColumns(scope, now)} rows={jobs} rowKey={(job) => job.runId}
          onOpen={(job) => setOpenRun(job.runId)} testId="octryx-jobs-table" />
      ) : null}
    </section>
  );
}
