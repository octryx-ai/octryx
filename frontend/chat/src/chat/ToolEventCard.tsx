// One tool event as a full card: status, badges, resume action, provenance, evidence, payload and outputs.

import { toolStatusLabel } from "./toolStatusLabel";
import type { ToolArtifact, ToolEvent } from "../chatThreadTypes";
import { extractEvidenceContract, extractToolProvenance, formatEvidenceContractBadge, formatProvenanceBadges } from "./traceToolEventValues";
import { ToolArtifacts } from "./messageBubbleToolArtifacts";
import { EvidenceContractSummary, ExecutionEventSummary } from "./toolEventSummaries";

export function ToolEventCard({ event, onRetryFromToolEvent, onPreviewArtifact, actionsDisabled }: {
  event: ToolEvent;
  onRetryFromToolEvent?: (event: ToolEvent) => void | Promise<void>;
  onPreviewArtifact?: (artifact: ToolArtifact) => void;
  actionsDisabled: boolean;
}) {
  return (
    <details className="tool-card">
      {(() => {
        const provenance = extractToolProvenance(event.result);
        const provenanceBadges = provenance
          ? formatProvenanceBadges(provenance)
          : [];
        const evidenceContract = extractEvidenceContract(event.result);
        const evidenceBadge = formatEvidenceContractBadge(evidenceContract);
        return (
          <summary className="tool-card__summary">
            <div>
              <div className="tool-card__name">{event.toolName}</div>
              <div className="tool-card__meta">
                <span>{toolStatusLabel(event.status)}</span>
                {event.durationMs ? (
                  <span>{event.durationMs} ms</span>
                ) : null}
                {event.artifacts?.length ? (
                  <span>
                    {event.artifacts.length} output
                    {event.artifacts.length === 1 ? "" : "s"}
                  </span>
                ) : null}
                {provenanceBadges.map((badge) => (
                  <span key={badge} className="tool-card__provenance-badge">
                    {badge}
                  </span>
                ))}
                {evidenceBadge ? (
                  <span
                    className={`tool-card__evidence-badge ${
                      String(evidenceContract?.status || "")
                        .trim()
                        .toLowerCase() === "passed"
                        ? "tool-card__evidence-badge--passed"
                        : "tool-card__evidence-badge--failed"
                    }`}
                  >
                    {evidenceBadge}
                  </span>
                ) : null}
              </div>
            </div>
            <div className="tool-card__summary-actions">
              {onRetryFromToolEvent && event.messageId ? (
                <button
                  type="button"
                  className="tool-card__action"
                  disabled={actionsDisabled}
                  onClick={(clickEvent) => {
                    clickEvent.preventDefault();
                    clickEvent.stopPropagation();
                    void onRetryFromToolEvent(event);
                  }}
                >
                  Resume from here
                </button>
              ) : null}
              <span className="tool-card__toggle">Details</span>
            </div>
          </summary>
        );
      })()}
      <div className="tool-card__body">
        {(() => {
          const provenance = extractToolProvenance(event.result);
          if (!provenance) {
            return null;
          }
          return (
            <section>
              <div className="tool-card__label">Provenance</div>
              <pre>{JSON.stringify(provenance, null, 2)}</pre>
            </section>
          );
        })()}
        <EvidenceContractSummary
          contract={extractEvidenceContract(event.result)}
        />
        <ExecutionEventSummary event={event} />
        <section>
          <div className="tool-card__label">Parameters</div>
          <pre>{JSON.stringify(event.parameters ?? {}, null, 2)}</pre>
        </section>
        <section>
          <div className="tool-card__label">Result</div>
          <pre>{JSON.stringify(event.result ?? {}, null, 2)}</pre>
        </section>
        {event.artifacts?.length ? (
          <section>
            <div className="tool-card__label">Outputs</div>
            <ToolArtifacts
              artifacts={event.artifacts}
              onPreviewArtifact={onPreviewArtifact}
            />
          </section>
        ) : null}
      </div>
    </details>
  );
}
