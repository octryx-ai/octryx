import type { ReactNode } from "react";
import type { ToolEvent } from "../chatThreadTypes";
import { foldToolSteps, type ToolStepFailure, type ToolStepFold as Fold } from "./toolStepFoldModel";
import { RemedyAction } from "./devices/RemedyAction";

// One line for all tool steps of a turn; the existing per-tool list (children) opens below it. Failed steps are
// listed unfolded, one line each.
export function ToolStepFold({ events, children }: { events: ToolEvent[]; children: ReactNode }) {
  const fold = foldToolSteps(events);
  return fold ? <ToolFoldView fold={fold}>{children}</ToolFoldView> : null;
}

/** The fold line itself, for any source of tool steps (chat turns, device jobs). */
export function ToolFoldView({ fold, children }: { fold: Fold; children: ReactNode }) {
  return (
    <div className="tool-fold" data-testid="tool-fold">
      <details className="tool-fold__details">
        <summary className="tool-fold__summary">{fold.label}</summary>
        <div className="tool-fold__body">{children}</div>
      </details>
      {fold.failures.length ? (
        <ul className="tool-fold__failures" aria-label="Failed tool steps">
          {fold.failures.map((failure) => (
            <li key={failure.id} className={`tool-fold__failure${failure.blocked ? " tool-fold__failure--blocked" : ""}`}>
              <FailureLine failure={failure} />
              {failure.remedy ? <RemedyAction remedy={failure.remedy} /> : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function FailureLine({ failure }: { failure: ToolStepFailure }) {
  if (!failure.blocked || !failure.raw) return <>{failure.text}</>;
  return (
    <details>
      <summary>{failure.text}</summary>
      <pre className="tool-fold__raw">{failure.raw}</pre>
    </details>
  );
}
