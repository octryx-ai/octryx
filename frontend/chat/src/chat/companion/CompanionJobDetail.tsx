import { useCallback, useEffect, useRef, useState } from "react";
import { formatExactTime, formatRelative } from "../../admin/utils/dateTime";
import { useConfirmAction } from "../../admin/components/confirm/useConfirmAction";
import { abortJob, emergencyStop, loadJob } from "./companionApi";
import { canEmergencyStop, canHandOver, handedOverText, handoverStatus } from "./companionHandoverModel";
import { CompanionHandover } from "./CompanionHandover";
import { currentSentence, eventViews, phaseStates, technicalCount } from "./companionEvents";
import { ItemCard } from "./CompanionItemCard";
import {
  canAbort,
  isStopped,
  jobErrorText,
  jobLink,
  jobProblemItem,
  jobStateLabel,
  jobTitle,
  PHASE_STATE_LABEL,
  phaseText,
  showsProblem,
  targetText,
  type JobDetail,
} from "./companionJobModel";

// One run, read-only, inside the panel: its phases, the current step and the run events (newest first), live while
// open through the attention socket's watch. Its owner can abort it (reason required, the run's own endpoint) or hand it
// over to another person; an admin can also stop it in an emergency (last, danger, reason required). Events read as
// sentences, technical ones behind "Show technical events"; a problem shows its reason and the owner's
// decisions from the job detail (problem, actions).

export type WatchJob = (runId: string | null, onChange?: () => void) => void;

type JobDetailProps = {
  runId: string; onBack: () => void; watchJob: WatchJob; isAdmin?: boolean; now?: () => number;
};

export function CompanionJobDetail({ runId, onBack, watchJob, isAdmin = false, now = Date.now }: JobDetailProps) {
  const state = useCompanionJob(runId, watchJob);
  const { job, problem, gone, reload } = state;
  return (
    <section className="octryx-panel__section" aria-label="Job" data-testid="octryx-job">
      <button type="button" className="admin-panel__action-btn octryx-jobs__back" onClick={onBack}>← All jobs</button>
      {problem ? (
        <div className="octryx-panel__section" role="status" data-testid="octryx-job-problem">
          <p className="octryx-panel__hint">{problem}</p>
          {gone ? null : <button type="button" className="admin-panel__action-btn" onClick={reload}>Try again</button>}
        </div>
      ) : null}
      {!job && !problem ? <p className="octryx-panel__hint" role="status">Loading the job…</p> : null}
      {job && !gone ? <JobBody job={job} state={state} isAdmin={isAdmin} now={now} /> : null}
    </section>
  );
}

// The panel's state, the confirmation and the live load of the run (a stale answer is dropped).
function useCompanionJob(runId: string, watchJob: WatchJob) {
  const [handingOver, setHandingOver] = useState(false);
  const [technical, setTechnical] = useState(false);
  const [handoverNotice, setHandoverNotice] = useState<string | null>(null);
  const [job, setJob] = useState<JobDetail | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [gone, setGone] = useState(false);
  const generation = useRef(0);
  const { ask, dialog, notice } = useConfirmAction();

  const reload = useCallback(() => {
    const run = ++generation.current;
    loadJob(runId).then((next) => {
      if (run !== generation.current) return;
      setProblem(null);
      setGone(false);
      setJob(next);
    }).catch((error: { status?: number }) => {
      if (run !== generation.current) return;
      setGone(error?.status === 404);
      setProblem(jobErrorText(error?.status));
    });
  }, [runId]);

  useEffect(() => {
    const loads = generation;
    reload();
    watchJob(runId, reload);
    return () => {
      loads.current++;
      watchJob(null);
    };
  }, [reload, runId, watchJob]);
  return { handingOver, setHandingOver, technical, setTechnical, handoverNotice, setHandoverNotice, job, problem, gone, ask, dialog,
    notice, reload };
}

type JobState = ReturnType<typeof useCompanionJob>;

// What the loaded run shows: its decision item, handover line and link.
function jobFacts(job: JobDetail, state: JobState, isAdmin: boolean) {
  // The reason and the owner's decisions come with the job detail.
  const problemItem = jobProblemItem(job);
  const inProblem = showsProblem(job);
  // A pending handover hides "Hand over…"; once accepted, only whoever controls the run now may hand it on.
  const handover = handoverStatus(job);
  const mayHandOver = canHandOver(job, isAdmin) && handover?.state !== "requested"
    && !(handover?.state === "accepted" && !job.canControl);
  const handoverLine = handover?.state === "accepted" && !job.canControl ? handedOverText(handover.owner) : state.handoverNotice;
  return { inProblem, problemItem, mayHandOver, handoverLine, link: jobLink(job) };
}

function JobBody({ job, state, isAdmin, now }: {
  job: JobDetail; state: JobState; isAdmin: boolean; now: () => number;
}) {
  const { technical, handingOver, setHandingOver, reload } = state;
  const title = jobTitle(job);
  const phases = phaseStates(job);
  const sentence = currentSentence(job);
  const facts = jobFacts(job, state, isAdmin);
  const { problemItem } = facts;
  return (
    <>
      <h3 className="octryx-panel__item-title">{title}</h3>
      <span className="octryx-panel__meta">
        {[jobStateLabel(job), phaseText(job), job.workspace?.name, job.owner?.name].filter(Boolean).join(" · ")}
      </span>
      {targetText(job.target) ? (
        <span className="octryx-panel__meta" data-testid="octryx-job-target">
          Runs {targetText(job.target)}{job.target?.folder ? ` (${job.target.folder})` : ""}
        </span>
      ) : null}
      {phases.length ? (
        <ol className="octryx-jobs__phases" aria-label="Phases" data-testid="octryx-job-phases">
          {phases.map((phase) => (
            <li key={phase.id} className={`octryx-jobs__phase octryx-jobs__phase--${phase.state}`} data-state={phase.state}>
              <span>{phase.title}</span>
              <span className="octryx-panel__meta">{PHASE_STATE_LABEL[phase.state]}</span>
            </li>
          ))}
        </ol>
      ) : null}
      {facts.inProblem ? (
        problemItem ? (
          <ul className="octryx-panel__list" data-testid="octryx-job-decision">
            <ItemCard item={problemItem} now={now()} answered={false}
              onAnswered={() => reload()}
              onAccepted={() => {}} />
          </ul>
        ) : (
          <p className="octryx-jobs__reason" data-testid="octryx-job-reason">
            {sentence || "The run stopped and needs a decision by its owner."}
          </p>
        )
      ) : sentence ? (
        <p className="octryx-panel__text" data-testid="octryx-job-step">
          <strong>{isStopped(job) ? "Stopped: " : "Now: "}</strong>{sentence}
        </p>
      ) : null}
      <JobEvents job={job} technical={technical} setTechnical={state.setTechnical} now={now} />
      <JobButtons job={job} title={title} state={state} isAdmin={isAdmin} facts={facts} />
      {handingOver ? (
        <CompanionHandover job={job} title={title} onClose={() => setHandingOver(false)}
          onRequested={(text) => { setHandingOver(false); state.setHandoverNotice(text); reload(); }} />
      ) : null}
      {facts.handoverLine ? <p className="octryx-panel__hint" role="status" data-testid="octryx-handover-notice">{facts.handoverLine}</p> : null}
      {state.notice}
      {state.dialog}
    </>
  );
}

// The run events, newest first; technical ones behind their toggle.
function JobEvents({ job, technical, setTechnical, now }: {
  job: JobDetail; technical: boolean; setTechnical: JobState["setTechnical"]; now: () => number;
}) {
  const views = eventViews(job.events, { technical });
  const technicalEvents = technicalCount(job.events);
  return (
    <>
      {views.length ? (
        <ul className={`octryx-jobs__events${technical ? " octryx-jobs__events--technical" : ""}`} aria-label="What happened" data-testid="octryx-job-events">
          {views.map((event, index) => (
            <li key={`${event.at ?? ""}-${index}`} data-technical={event.technical || undefined}>
              <span>{event.text}{event.count > 1 ? ` ×${event.count}` : ""}</span>
              {event.at ? <span className="octryx-panel__meta" title={formatExactTime(event.at)}>{formatRelative(event.at, "", now())}</span> : null}
            </li>
          ))}
        </ul>
      ) : null}
      {technicalEvents ? (
        <button type="button" className="admin-panel__action-btn octryx-jobs__back" aria-pressed={technical}
          data-testid="octryx-job-technical" onClick={() => setTechnical((value) => !value)}>
          {technical ? "Hide technical events" : `Show technical events (${technicalEvents})`}
        </button>
      ) : null}
    </>
  );
}

// Link, hand over, abort (owner, reason required) and emergency stop (admin, last, reason required).
function JobButtons({ job, title, state, isAdmin, facts }: {
  job: JobDetail; title: string; state: JobState; isAdmin: boolean; facts: ReturnType<typeof jobFacts>;
}) {
  const { ask, reload, handingOver } = state;
  const { link, mayHandOver, problemItem } = facts;
  const abort = () => job && ask({
    title: `Abort the run "${title}"?`,
    body: <p>The run stops where it stands and cannot be continued. Your reason is recorded on the run.</p>,
    confirmLabel: "Abort run", tone: "danger",
    field: { label: "Reason", placeholder: "e.g. Wrong branch, I start it again", required: true },
    run: (reason) => abortJob(job.runId, reason).then(reload),
    done: `Run "${title}" aborted.`,
  });
  const stop = () => job && ask({
    title: `Emergency stop of the run "${title}"?`,
    body: <p>The run and its device job stop at once and cannot be continued. Your reason is recorded in the audit log.</p>,
    confirmLabel: "Emergency stop", tone: "danger",
    field: { label: "Reason", placeholder: "e.g. The run writes to the wrong system", required: true },
    run: (reason) => emergencyStop(job.runId, reason).then(reload),
    done: `Run "${title}" stopped.`,
  });
  return (
    <div className="octryx-panel__buttons">
      {link ? <a className="admin-panel__action-btn" href={link.href}>{link.label} →</a> : null}
      {mayHandOver && !handingOver ? (
        <button type="button" className="admin-panel__action-btn" data-testid="octryx-job-handover"
          onClick={() => { state.setHandoverNotice(null); state.setHandingOver(true); }}>
          Hand over…
        </button>
      ) : null}
      {canAbort(job) && !problemItem ? (
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--danger" onClick={abort}
          data-testid="octryx-job-abort">
          Abort run
        </button>
      ) : null}
      {canEmergencyStop(job, isAdmin) ? (
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--danger" onClick={stop}
          data-testid="octryx-job-emergency-stop">
          Emergency stop
        </button>
      ) : null}
    </div>
  );
}
