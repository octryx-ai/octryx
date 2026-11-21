// A compact tool burst: the grouped attempts of one tool as a disclosure with its status, stats and steps.

import { toolStatusLabel } from "./toolStatusLabel";
import type { ToolArtifact, ToolEvent } from "../chatThreadTypes";
import { countToolArtifacts, groupToolEvents, summarizeToolGroup } from "./traceUiHelpers";
import { formatDurationMs, humanizeToolName } from "./traceToolEventValues";
import { ToolBurstEvent } from "./ToolBurstEvent";

function summarizeToolGroupStatus(value: string) {
  return toolStatusLabel(value);
}
type ToolGroup = ReturnType<typeof groupToolEvents>[number];

const eventStatus = (event: ToolEvent) =>
  String(event.status || "")
    .trim()
    .toLowerCase();

// Names, duration, outputs, status and per-status counts of one burst.
function toolBurstFigures(group: ToolGroup) {
  const toolNames = Array.from(
    new Set(
      group.events
        .map((event) => humanizeToolName(event.toolName))
        .filter(Boolean),
    ),
  );
  const totalDuration = formatDurationMs(
    group.events.reduce(
      (total, event) => total + Number(event.durationMs || 0),
      0,
    ),
  );
  const previewLabel = toolNames.slice(0, 2).join(" · ");
  const disclosureLabel =
    toolNames[0] ||
    humanizeToolName(group.events[0].toolName) ||
    "Tool usage";
  const statusLabel = summarizeToolGroupStatus(group.status);
  const countOf = (...states: string[]) =>
    group.events.filter((event) => states.includes(eventStatus(event))).length;
  const successCount = countOf("success", "completed");
  const errorCount = countOf("error", "failed");
  const runningCount = countOf("running", "pending");
  const compactStatusTitle =
    group.status === "mixed"
      ? `${successCount} successful, ${errorCount} failed`
      : statusLabel;
  return {
    totalDuration,
    artifactCount: countToolArtifacts(group.events),
    previewLabel,
    disclosureLabel,
    statusLabel,
    compactStatusTitle,
    summaryStats: summaryStatsOf(group.events.length, successCount, errorCount, runningCount),
  };
}

function summaryStatsOf(attempts: number, successCount: number, errorCount: number, runningCount: number) {
  const summaryStats: string[] = [];
  if (attempts > 1) {
    summaryStats.push(`${attempts} attempts`);
  } else {
    summaryStats.push("1 step");
  }
  if (successCount) {
    summaryStats.push(`${successCount} ok`);
  }
  if (errorCount) {
    summaryStats.push(
      `${errorCount} error${errorCount === 1 ? "" : "s"}`,
    );
  }
  if (runningCount) {
    summaryStats.push(`${runningCount} active`);
  }
  return summaryStats;
}

type Figures = ReturnType<typeof toolBurstFigures>;

function ToolBurstSummary({ group, figures }: { group: ToolGroup; figures: Figures }) {
  const { disclosureLabel, previewLabel, totalDuration, compactStatusTitle, statusLabel } = figures;
  return (
    <summary className="tool-burst__summary">
      <div className="tool-burst__summary-main">
        <div className="tool-burst__cardline">
          <span
            className="tool-burst__summary-icon"
            aria-hidden="true"
          >
            {">"}
          </span>
          <div className="tool-burst__summary-copyblock">
            <span className="tool-burst__prompt-copy">
              {disclosureLabel}
            </span>
            {previewLabel && previewLabel !== disclosureLabel ? (
              <span className="tool-burst__context">
                {previewLabel}
              </span>
            ) : null}
          </div>
        </div>
      </div>
      <div className="tool-burst__summary-meta">
        {totalDuration ? (
          <span className="tool-burst__duration">
            {totalDuration}
          </span>
        ) : null}
        <span
          className={`tool-burst__status tool-burst__status--${group.status.toLowerCase()}`}
          title={compactStatusTitle}
        >
          {statusLabel}
        </span>
        <span className="tool-burst__toggle">
          <span className="tool-burst__caret" aria-hidden="true">
            {">"}
          </span>
        </span>
      </div>
    </summary>
  );
}

function ToolBurstBodySummary({ group, figures }: { group: ToolGroup; figures: Figures }) {
  const { previewLabel, summaryStats, artifactCount, totalDuration } = figures;
  return (
    <div className="tool-burst__body-summary">
      <div className="tool-burst__headline-row">
        <span className="tool-burst__title">
          {previewLabel || "Tool usage"}
        </span>
      </div>
      <div className="tool-burst__copy">
        {summarizeToolGroup(group.events)}
      </div>
      <div className="tool-burst__summary-stats">
        {summaryStats.map((item) => (
          <span key={item} className="tool-burst__count">
            {item}
          </span>
        ))}
        {artifactCount ? (
          <span className="tool-burst__meta">
            {artifactCount} output{artifactCount === 1 ? "" : "s"}
          </span>
        ) : null}
        {totalDuration ? (
          <span className="tool-burst__duration">
            {totalDuration}
          </span>
        ) : null}
      </div>
    </div>
  );
}

export function ToolBurst({ group, onRetryFromToolEvent, onPreviewArtifact, actionsDisabled }: {
  group: ToolGroup;
  onRetryFromToolEvent?: (event: ToolEvent) => void | Promise<void>;
  onPreviewArtifact?: (artifact: ToolArtifact) => void;
  actionsDisabled: boolean;
}) {
  const figures = toolBurstFigures(group);
  return (
    <details className="tool-burst">
      <ToolBurstSummary group={group} figures={figures} />
      <div className="tool-burst__body">
        <ToolBurstBodySummary group={group} figures={figures} />
        {group.events.map((event, index) => (
          <ToolBurstEvent key={event.id} event={event} index={index} onRetryFromToolEvent={onRetryFromToolEvent}
            onPreviewArtifact={onPreviewArtifact} actionsDisabled={actionsDisabled} />
        ))}
      </div>
    </details>
  );
}
