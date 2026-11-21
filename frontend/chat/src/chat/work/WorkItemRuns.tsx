import { useEffect, useState } from "react";

import "../workflowRun/workflowRun.css";
import { readJson } from "../chatApiClient";
import { chatSessionHref, followUpFailure, INSTALL_LAUNCHER_HREF, runStopText, SAMPLE_RUN_LABEL, SAMPLE_RUN_TEXT, sampleRunBadge, opensChat } from "../workflowRun/workflowRunModel";
import { runFlagText, runStatusLabel, runStatusTone } from "../workflowRun/workflowRunStatus";
import { runsForWorkItemPath } from "../workflowRun/workflowRunRequests";
import { type RunRow } from "../workflowRun/workflowRunTypes";
import { DetailSection } from "./WorkItemDetailParts";
import type { WorkItem } from "./workItemTypes";

// The newest runs shown on Overview; the rest are counted, never listed (the panel stays short).
export const RUNS_SHOWN = 5;

// The Work item's workflow runs (S1 anchor) on Overview: a short list of the runs started for it, newest first, with
// a "Run paused" flag. Nothing at all while the item has none; starting a run is the header's "Start workflow"
// (WorkItemRunStart), never a form here.
export function WorkItemRuns({ item }: { item: WorkItem }) {
  const [runs, setRuns] = useState<RunRow[]>([]);

  useEffect(() => {
    let cancelled = false;
    void readJson<{ runs: RunRow[] }>(runsForWorkItemPath(item.id))
      .then((payload) => !cancelled && setRuns(payload.runs || []))
      .catch(() => !cancelled && setRuns([]));
    return () => {
      cancelled = true;
    };
  }, [item.id]);

  if (!runs.length) return null;
  const hidden = runs.length - RUNS_SHOWN;
  return (
    <DetailSection title="Workflow runs">
      <div className="work-detail__runs" data-testid="work-detail-runs">
        <ul className="workflow-run-list">
          {runs.slice(0, RUNS_SHOWN).map((run) => {
            const flag = runFlagText(run);
            return (
              <li key={run.id}>
                <span>{run.title}</span>{" "}
                {sampleRunBadge(run) ? (
                  <>
                    <span className="work-badge work-badge--info" title={SAMPLE_RUN_TEXT}>{SAMPLE_RUN_LABEL}</span>{" "}
                  </>
                ) : null}
                <span
                  className={`work-badge work-badge--${runStatusTone(run.status)}`}
                >
                  {flag ?? runStatusLabel(run)}
                </span>{" "}
                {runStopText(run) ? <span className="work-detail__empty">{runStopText(run)}</span> : null}{" "}
                {followUpFailure(run) ? (
                  <span className="work-detail__empty" role="alert">
                    {followUpFailure(run)?.text}
                    {followUpFailure(run)?.needsDevice ? (
                      <>
                        {" "}
                        <a href={INSTALL_LAUNCHER_HREF}>Pair Claude Code with the launcher</a>
                      </>
                    ) : null}
                  </span>
                ) : null}{" "}
                {run.session_id && opensChat(run) ? (
                  <a href={chatSessionHref(run.session_id)}>Open the chat</a>
                ) : null}
              </li>
            );
          })}
        </ul>
        {hidden > 0 ? (
          <p className="work-detail__empty">{hidden === 1 ? "1 earlier run" : `${hidden} earlier runs`}</p>
        ) : null}
      </div>
    </DetailSection>
  );
}
