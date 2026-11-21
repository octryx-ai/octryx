import { toolStatusLabel } from "./toolStatusLabel";
import type { DecisionTimelineEvent, TurnTrace } from "../chatThreadTypes";
import { TraceValue } from "./traceUiComponents";

function isDecisionTimelineEvent(value: unknown): value is DecisionTimelineEvent {
  if (!value || typeof value !== "object") {
    return false;
  }
  const event = value as Partial<DecisionTimelineEvent>;
  return Boolean(event.phase && event.title && event.status);
}

function decisionTimelineFromTrace(trace: TurnTrace): DecisionTimelineEvent[] {
  const rawTimeline = trace.contextSnapshot?.decision_timeline;
  if (!Array.isArray(rawTimeline)) {
    return [];
  }
  return rawTimeline.filter(isDecisionTimelineEvent);
}

function statusClassName(status: string) {
  const normalized = String(status || "info")
    .trim()
    .toLowerCase();
  if (["ok", "success", "completed"].includes(normalized)) {
    return "turn-decision-timeline__status turn-decision-timeline__status--ok";
  }
  if (["error", "failed", "blocked"].includes(normalized)) {
    return "turn-decision-timeline__status turn-decision-timeline__status--error";
  }
  if (["pending", "waiting"].includes(normalized)) {
    return "turn-decision-timeline__status turn-decision-timeline__status--pending";
  }
  return "turn-decision-timeline__status";
}

export function TraceDecisionTimeline({ trace }: { trace: TurnTrace }) {
  const timeline = decisionTimelineFromTrace(trace);
  if (!timeline.length) {
    return null;
  }
  return (
    <section className="turn-trace-section turn-decision-timeline">
      <h4>Decision Timeline</h4>
      <ol className="turn-decision-timeline__list">
        {timeline.map((event, fallbackIndex) => (
          <li
            key={`${event.index ?? fallbackIndex}-${event.phase}-${event.title}`}
            className="turn-decision-timeline__item"
          >
            <div className="turn-decision-timeline__marker">
              {event.index ?? fallbackIndex + 1}
            </div>
            <div className="turn-decision-timeline__body">
              <div className="turn-decision-timeline__head">
                <span className="turn-decision-timeline__phase">
                  {event.phase}
                </span>
                <span className={statusClassName(event.status)}>
                  {toolStatusLabel(event.status)}
                </span>
              </div>
              <div className="turn-decision-timeline__title">
                {event.title}
              </div>
              {event.detail ? (
                <div className="turn-decision-timeline__detail">
                  {event.detail}
                </div>
              ) : null}
              {event.metadata ? (
                <details className="turn-decision-timeline__metadata">
                  <summary>Metadata</summary>
                  <TraceValue value={event.metadata} />
                </details>
              ) : null}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

