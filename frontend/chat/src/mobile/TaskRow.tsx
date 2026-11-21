// One task in a list (Home and Open tasks): the ticket, its state, who has it, and its run when there is one.

import { runStatusLabel } from "../chat/workflowRun/workflowRunStatus";
import { sourceLabel, stateLabel, type Case } from "./mobileTasksModel";

function dot(item: Case): string {
  const status = item.run?.status;
  if (status === "waiting" || status === "paused") return "m-dot-need";
  if (status === "running") return "m-dot-blue";
  if (status === "failed") return "m-dot-red";
  return item.state === "blocked" ? "m-dot-red" : "m-dot-idle";
}

export function TaskRow({
  item,
  workspace = "",
  onOpen,
}: {
  item: Case;
  workspace?: string;
  onOpen: (item: Case) => void;
}) {
  const run = item.run
    ? runStatusLabel({
        status: item.run.status,
        outcome: item.run.outcome,
        waiting_kind: item.run.waitingKind,
        pause_reason: item.run.pauseReason,
      })
    : "";
  const owner = item.run?.responsible ? `Responsible ${item.run.responsible.name}` : item.assignee;
  const detail = [stateLabel(item.state), run && `Run: ${run}`, owner, item.priority].filter(Boolean).join(" · ");
  const where = [workspace, sourceLabel(item.source)].filter(Boolean).join(" · ");
  return (
    <li>
      <button type="button" className="m-row" onClick={() => onOpen(item)}>
        <i className={`m-dot ${dot(item)}`} aria-hidden="true" />
        <span className="m-row-text">
          <b>
            {item.key} · {item.title}
          </b>
          <span>{detail}</span>
          {where && <span className="m-row-where">{where}</span>}
        </span>
        {item.automatic && <span className="m-tag">Auto</span>}
      </button>
    </li>
  );
}
