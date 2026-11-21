import type { ReactNode } from "react";

import { TimeText } from "../../admin/utils/TimeText";
import { STEP_STATE_LABEL, type CodingSectionKey, type CodingStepState } from "./codingSessionSteps";

const STATE_TONE: Record<CodingStepState, string> = { done: "active", active: "running", problem: "danger", pending: "neutral",
  stopped: "neutral" };

// One step (or closing section) of the Coding session: a header line with state, one-line summary and time, the
// evidence only while it is open. A closed step renders no body, so its evidence loads only when someone opens it.
export function CodingStepSection({
  sectionKey,
  title,
  state,
  summary,
  at,
  open,
  onToggle,
  children,
}: {
  sectionKey: CodingSectionKey;
  title: string;
  state?: CodingStepState;
  summary: string;
  at?: string | null;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  const stateLabel = state ? STEP_STATE_LABEL[state] : "";
  return (
    <section
      className={`coding-step ${state ? `is-${state}` : "is-section"}${open ? " is-open" : ""}`}
      aria-label={state ? `${title}: ${stateLabel}` : title}
      data-testid={`coding-step-${sectionKey}`}
    >
      <button type="button" className="coding-step__head" aria-expanded={open} onClick={onToggle}>
        <span className="coding-step__marker" aria-hidden="true" />
        <span className="coding-step__title">{title}</span>
        {state ? <span className={`work-badge work-badge--${STATE_TONE[state]}`}>{stateLabel}</span> : null}
        <span className="coding-step__summary">{summary}</span>
        {at ? <TimeText value={at} className="coding-step__time" /> : null}
        <span className="coding-step__chevron" aria-hidden="true">{open ? "▾" : "▸"}</span>
      </button>
      {open ? <div className="coding-step__body">{children}</div> : null}
    </section>
  );
}
