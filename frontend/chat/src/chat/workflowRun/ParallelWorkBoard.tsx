import { StatusLabel } from "../../layout/StatusLabel";
import { workItemRows, workPlanned, workSummary, type TeamWork } from "./teamworkModel";
import { chatSessionHref } from "./workflowRunModel";
import { type RunNode } from "./workflowRunTypes";

type ParallelWorkBoardProps = {
  work: TeamWork | null | undefined;
  nodes: RunNode[];
  currentNode: RunNode | null;
};

// Teamwork (WP-D, mock board 12): the "Parallel work" box opened into the items the coordinator's plan really runs,
// one card per item with role, model, status, round and what it waits for. Before the plan the box only says that
// the split happens at run time. A card links to the item's own chat once its agent started.
export function ParallelWorkBoard({ work, nodes, currentNode }: ParallelWorkBoardProps) {
  const planned = workPlanned(work);
  const onBox = currentNode?.kind === "parallel_work";
  if (!planned && !onBox) return null;
  const node = nodes.find((item) => item.id === work?.node_id) ?? (onBox ? currentNode : null);
  const title = node?.title || "Parallel work";
  if (!planned) {
    return (
      <section className="parallel-work parallel-work--unplanned" aria-label={title} data-testid="parallel-work">
        <div className="parallel-work__head">
          <span className="parallel-work__title">{title}</span>
          <span className="parallel-work__summary">split at run time · the coordinator has not planned yet</span>
        </div>
      </section>
    );
  }
  const rows = workItemRows(work);
  const version = work?.plan_version ? `plan v${work.plan_version}` : "";
  return (
    <section className="parallel-work" aria-label={title} data-testid="parallel-work">
      <div className="parallel-work__head">
        <span className="parallel-work__title">{title}</span>
        <span className="parallel-work__summary">{[workSummary(work), version].filter(Boolean).join(" · ")}</span>
      </div>
      <ol className="parallel-work__items">
        {rows.map((row) => (
          <li key={row.id} className={`parallel-work__item parallel-work__item--${row.tone}`} data-status={row.status}
            data-testid="parallel-work-item">
            <span className="parallel-work__kind">{[row.role, row.model].filter(Boolean).join(" · ")}</span>
            <span className="parallel-work__item-title">
              {row.sessionId ? <a href={chatSessionHref(row.sessionId)}>{row.title}</a> : row.title}
            </span>
            {row.after ? (
              <span className="parallel-work__note parallel-work__after" title={row.afterAll}>
                <span className="parallel-work__after-first">after {row.afterFirst}</span>
                {row.afterMore ? <span className="parallel-work__after-more">+{row.afterMore}</span> : null}
              </span>
            ) : null}
            {row.detail ? <span className="parallel-work__note parallel-work__note--detail">{row.detail}</span> : null}
            <span className="parallel-work__marks">
              <StatusLabel label={row.status === "merged" ? "✓ Merged" : row.label} tone={row.tone} />
              {row.round ? <span className="parallel-work__round">{row.round}</span> : null}
              {row.branch ? <code className="parallel-work__branch" title={row.branch}>{row.branch}</code> : null}
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}
