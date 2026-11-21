// One step of a compact tool burst: name, summary, badges, resume action, outputs and payload.

import type { ToolArtifact, ToolEvent } from "../chatThreadTypes";
import { extractEvidenceContract, extractToolProvenance, formatEvidenceContractBadge, formatDateTime, formatProvenanceBadges, humanizeToolName } from "./traceToolEventValues";
import { summarizeToolEvent, summarizeToolEventMeta } from "./traceUiHelpers";
import { ToolArtifacts } from "./messageBubbleToolArtifacts";
import { EvidenceContractSummary, ExecutionEventSummary } from "./toolEventSummaries";

export function ToolBurstEvent({ event, index, onRetryFromToolEvent, onPreviewArtifact, actionsDisabled }: {
  event: ToolEvent;
  index: number;
  onRetryFromToolEvent?: (event: ToolEvent) => void | Promise<void>;
  onPreviewArtifact?: (artifact: ToolArtifact) => void;
  actionsDisabled: boolean;
}) {
  const summary = summarizeToolEvent(event);
  const provenance = extractToolProvenance(event.result);
  const provenanceBadges = provenance
    ? formatProvenanceBadges(provenance)
    : [];
  const evidenceContract = extractEvidenceContract(
    event.result,
  );
  const evidenceBadge =
    formatEvidenceContractBadge(evidenceContract);
  const eventMeta = summarizeToolEventMeta(event);
  const hasParameters = Boolean(
    event.parameters && Object.keys(event.parameters).length,
  );
  const hasResult = Boolean(
    event.result && Object.keys(event.result).length,
  );
  return (
    <section key={event.id} className="tool-burst__event">
      <div className="tool-burst__event-header">
        <div className="tool-burst__event-main">
          <div className="tool-burst__event-topline">
            <span className="tool-burst__event-index">
              {index + 1}
            </span>
            <div className="tool-burst__event-name">
              {humanizeToolName(event.toolName)}
            </div>
          </div>
          {summary ? (
            <div className="tool-burst__event-summary">
              {summary}
            </div>
          ) : null}
          <div className="tool-burst__event-meta">
            {eventMeta.map((item) => (
              <span key={item}>{item}</span>
            ))}
            <span title={formatDateTime(event.createdAt)}>
              {formatDateTime(event.createdAt)}
            </span>
            {provenanceBadges.map((badge) => (
              <span
                key={badge}
                className="tool-burst__provenance-badge"
              >
                {badge}
              </span>
            ))}
            {evidenceBadge ? (
              <span
                className={`tool-burst__evidence-badge ${
                  String(evidenceContract?.status || "")
                    .trim()
                    .toLowerCase() === "passed"
                    ? "tool-burst__evidence-badge--passed"
                    : "tool-burst__evidence-badge--failed"
                }`}
              >
                {evidenceBadge}
              </span>
            ) : null}
          </div>
        </div>
        {onRetryFromToolEvent && event.messageId ? (
          <div className="tool-burst__event-actions">
            <button
              type="button"
              className="tool-card__action"
              disabled={actionsDisabled}
              onClick={() => void onRetryFromToolEvent(event)}
            >
              Resume from here
            </button>
          </div>
        ) : null}
      </div>
      {event.artifacts?.length ? (
        <ToolArtifacts
          artifacts={event.artifacts}
          onPreviewArtifact={onPreviewArtifact}
        />
      ) : null}
      <EvidenceContractSummary contract={evidenceContract} />
      <ExecutionEventSummary event={event} />
      {hasParameters || hasResult ? (
        <details className="tool-burst__payload">
          <summary className="tool-burst__payload-toggle">
            <span>Payload</span>
            <span className="tool-burst__payload-hint">
              {hasParameters && hasResult
                ? "parameters + result"
                : hasParameters
                  ? "parameters"
                  : "result"}
            </span>
          </summary>
          <div className="tool-burst__payload-grid">
            {hasParameters ? (
              <section>
                <div className="tool-card__label">
                  Parameters
                </div>
                <pre>
                  {JSON.stringify(event.parameters, null, 2)}
                </pre>
              </section>
            ) : null}
            {hasResult ? (
              <section>
                <div className="tool-card__label">Result</div>
                <pre>
                  {JSON.stringify(event.result, null, 2)}
                </pre>
              </section>
            ) : null}
          </div>
        </details>
      ) : null}
    </section>
  );
}
