// A workflow run on the phone: its state, the decision it waits for (answered here), the Parallel work
// items as the coordinator split them (teamworkModel, as the web's board), every step of the workflow, the tasks and
// the run's own actions. Polled while it is not finished.

import { decisionCard, CARD_ACTION_KEYS } from "../chat/workflowRun/decisionCardModel";
import { runWorkflowName } from "../chat/workflowRun/runBarModel";
import { workPlanned } from "../chat/workflowRun/teamworkModel";
import { payloadView } from "../chat/workflowRun/workflowRunPayloadView";
import { DecisionCard } from "./DecisionCard";
import { SpecStudioLink } from "../chat/specStudio/SpecStudioLink";
import { OpenFindings } from "./OpenFindings";
import { runMainSession } from "./mobileRuns";
import { DetailHeader } from "./PageHeader";
import { RunActions } from "./RunActions";
import { RunPageLinks } from "./RunPageLinks";
import { RunParallelWork, RunSteps, RunSummary, RunTasks } from "./RunPageSections";
import { RunPayload } from "./RunPayload";
import { RunTokens } from "../chat/workflowRun/RunTokens";
import { useRunPage, type RunPayload as RunData } from "./useRunPage";

export type RunLinks = {
  onOpenChat: (sessionId: string, title: string, projectId: string) => void;
  onOpenWorkItem: (item: { id: string; key: string; title: string; state: string; projectId: string }) => void;
};

function RunWaiting({ run, acted }: { run: RunData; acted: ReturnType<typeof useRunPage>["acted"] }) {
  const card = decisionCard(run.waiting);
  const payload = run.waiting ? payloadView(run.waiting) : null;
  if (card) {
    return <DecisionCard key={run.waiting?.payload_hash ?? run.updated_at ?? ""} run={run} card={card} payload={payload} onDone={acted} />;
  }
  if (!(run.waiting && (run.waiting.question || run.waiting.title || payload) && run.status === "waiting")) return null;
  return (
    <section className="m-panel m-waiting">
      <span className="m-eyebrow">Waiting</span>
      {(run.waiting.question || run.waiting.title) && <p>{run.waiting.question || run.waiting.title}</p>}
      <RunPayload view={payload} />
    </section>
  );
}

export function RunPage({ runId, title, onBack, links }: { runId: string; title: string; onBack: () => void; links: RunLinks }) {
  const { run, error, sent, finished, acted } = useRunPage(runId);
  const subject = run?.work_item ? `${run.work_item.key} · ${run.work_item.title}` : run?.title || title;
  const card = run ? decisionCard(run.waiting) : null;
  const session = run ? runMainSession(run) : "";

  return (
    <div className="m-screen">
      <DetailHeader title={subject || "Run"} subtitle={run ? runWorkflowName(run) : undefined} onBack={onBack} />
      <main className="m-body">
        {error && (
          <p className="m-banner m-banner-problem" role="alert">
            {error}
          </p>
        )}
        {!run && !error && <p className="m-empty">Loading the run…</p>}
        {run && (
          <>
            {sent && (
              <p className="m-banner m-banner-info" role="status">
                {sent}
              </p>
            )}
            <RunSummary run={run} finished={finished} />
            <OpenFindings value={run.open_findings} />
            <SpecStudioLink runId={run.id} summary={run.spec_studio} className="m-primary m-studio-link" />
            <RunWaiting run={run} acted={acted} />
            {workPlanned(run.work) && <RunParallelWork run={run} links={links} />}
            <RunSteps run={run} />
            {run.task_list?.length ? <RunTasks tasks={run.task_list} /> : null}
            <section className="m-panel" aria-label="Tokens">
              <RunTokens runId={run.id} refreshKey={run.updated_at} />
            </section>
            <RunActions run={run} hide={card ? CARD_ACTION_KEYS : []} onDone={acted} />
            <RunPageLinks run={run} session={session} subject={subject} links={links} />
          </>
        )}
      </main>
    </div>
  );
}
