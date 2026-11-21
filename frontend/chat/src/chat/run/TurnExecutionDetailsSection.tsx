import type {
  TurnExecutionSummary,
  TurnExecutionSummaryLoad,
} from "./turnExecutionSummary.types";
import {
  presentNextAction,
  presentRunCapability,
  presentTurnExecutionState,
} from "./turnExecutionSummaryPresentation";
import { turnApprovalLabel } from "./turnExecutionSummaryParse";
import { TurnRunIdentityRow } from "./TurnRunIdentityRow";
import { presentEndReason, readableCode } from "./turnRunIdentityPresentation";

// Bounded execution section for the trace detail surface. It renders only the
// allow-listed summary fields; raw trace content is never passed in here.

function formatBytes(value: number | null) {
  if (value === null) {
    return null;
  }
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function capabilityCounts(
  capability: TurnExecutionSummary["capabilitiesUsed"][number],
) {
  const parts = [
    capability.calls !== null ? `${capability.calls} calls` : null,
    capability.succeeded !== null ? `${capability.succeeded} succeeded` : null,
    capability.failed ? `${capability.failed} failed` : null,
  ].filter(Boolean);
  return parts.length ? parts.join(" · ") : null;
}

function Field({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="turn-exec-details__field">
      <dt>{label}</dt>
      <dd>{value ?? "—"}</dd>
    </div>
  );
}

function SummaryBody({ summary }: { summary: TurnExecutionSummary }) {
  return (
    <>
      <SummaryFields summary={summary} />
      <h5 className="turn-exec-details__subhead">Run</h5>
      <TurnRunIdentityRow identity={summary.runIdentity} />
      <h5 className="turn-exec-details__subhead">Execution profile</h5>
      <ExecutionProfile summary={summary} />
      <h5 className="turn-exec-details__subhead">Capabilities used</h5>
      <CapabilitiesList summary={summary} />
      <h5 className="turn-exec-details__subhead">Approvals</h5>
      <ApprovalsList summary={summary} />
      <h5 className="turn-exec-details__subhead">Artifacts</h5>
      <ArtifactsList summary={summary} />
    </>
  );
}

function SummaryFields({ summary }: { summary: TurnExecutionSummary }) {
  const state = presentTurnExecutionState(summary.state);
  const { tokensIn, tokensOut } = summary.usage;
  return (
    <>
      <dl className="turn-exec-details__grid">
        <Field label="State" value={state.label} />
        <Field label="Reason" value={summary.stateReason.text} />
        <Field label="Next action" value={presentNextAction(summary.nextAction)} />
        <Field label="Agent" value={summary.agentName} />
        <Field label="Model" value={summary.modelLabel} />
        <Field label="Tokens" value={tokensIn === null && tokensOut === null ? null : `${tokensIn ?? "—"} in / ${tokensOut ?? "—"} out`} />
      </dl>
    </>
  );
}

function ExecutionProfile({ summary }: { summary: TurnExecutionSummary }) {
  const profile = summary.executionProfile;
  const endReasonCode =
    summary.runIdentity.kind === "product_run" && summary.runIdentity.attempt
      ? presentEndReason(summary.runIdentity.attempt.endReason)
      : null;
  return (
    <>
      {profile ? (
        <>
          <dl className="turn-exec-details__grid">
            <Field label="Profile" value={readableCode(profile.profileId)} />
            <Field label="Status" value={readableCode(profile.status)} />
            <Field label="Workflow" value={profile.workflowKey} />
            <Field label="Strategy" value={readableCode(profile.executionStrategy)} />
            <Field label="Run capability" value={presentRunCapability(profile.runCapability)} />
            <Field label="Gate outcome" value={readableCode(profile.gate?.outcome)} />
          </dl>
          {/* Raw codes for support: the readable labels above, the stored values here. */}
          <details className="turn-exec-details__technical">
            <summary>Technical details</summary>
            <dl className="turn-exec-details__grid">
              <Field label="Profile id" value={profile.profileId} />
              <Field label="Status code" value={profile.status} />
              <Field label="Decision source" value={profile.decisionSource} />
              <Field label="Strategy code" value={profile.executionStrategy} />
              <Field label="Capability source" value={profile.runCapability?.source ?? null} />
              <Field label="Contract" value={profile.version} />
              <Field label="Gate outcome code" value={profile.gate?.outcome ?? null} />
              <Field label="Gate status" value={profile.gate?.status ?? null} />
              <Field label="Gate source" value={profile.gate?.decisionSource ?? null} />
              {endReasonCode ? <Field label="End reason code" value={endReasonCode} /> : null}
            </dl>
          </details>
        </>
      ) : (
        <p className="turn-exec-details__empty">
          No execution profile was recorded for this turn.
        </p>
      )}
    </>
  );
}

function CapabilitiesList({ summary }: { summary: TurnExecutionSummary }) {
  return (
    <>
      {summary.capabilitiesUsed.length ? (
        <ul className="turn-exec-details__list">
          {summary.capabilitiesUsed.map((capability, index) => (
            <li key={`${capability.name}-${index}`}>
              <span>{capability.name}</span>
              {capabilityCounts(capability) ? (
                <span className="turn-exec-details__muted">
                  {capabilityCounts(capability)}
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="turn-exec-details__empty">None recorded.</p>
      )}
    </>
  );
}

function ApprovalsList({ summary }: { summary: TurnExecutionSummary }) {
  return (
    <>
      {summary.approvals.length ? (
        <ul className="turn-exec-details__list">
          {summary.approvals.map((approval, index) => (
            <li key={approval.id ?? `approval-${index}`}>
              <span>{turnApprovalLabel(approval)}</span>
              {approval.status ? (
                <span className="turn-exec-details__tag">
                  {approval.status}
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="turn-exec-details__empty">None recorded.</p>
      )}
    </>
  );
}

function ArtifactsList({ summary }: { summary: TurnExecutionSummary }) {
  return (
    <>
      {summary.artifacts.length ? (
        <ul className="turn-exec-details__list">
          {summary.artifacts.map((artifact, index) => (
            <li key={artifact.id ?? `artifact-${index}`}>
              <span>{artifact.toolName ?? "Tool artifact"}</span>
              {artifact.id ? (
                <span className="turn-exec-details__tag">{artifact.id}</span>
              ) : null}
              {artifact.sizeBytes !== null ? (
                <span className="turn-exec-details__muted">
                  {formatBytes(artifact.sizeBytes)}
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="turn-exec-details__empty">None recorded.</p>
      )}
    </>
  );
}

export function TurnExecutionDetailsSection({
  load,
  onRetry,
}: {
  load: TurnExecutionSummaryLoad;
  onRetry?: () => void;
}) {
  if (load.status === "idle") {
    return null;
  }
  return (
    <section
      className="turn-trace-section turn-exec-details"
      aria-label="Execution summary"
    >
      <h4>Execution summary</h4>
      {load.status === "loading" ? (
        <p className="turn-exec-details__empty" aria-busy="true">
          Loading execution summary…
        </p>
      ) : load.status === "error" ? (
        <p className="turn-exec-details__empty" role="alert">
          Execution summary could not be loaded.{" "}
          {onRetry ? (
            <button
              type="button"
              className="turn-exec-card__action"
              onClick={onRetry}
            >
              Retry
            </button>
          ) : null}
        </p>
      ) : load.status === "unavailable" ? (
        <p className="turn-exec-details__empty">
          No execution summary is available for this turn.
        </p>
      ) : (
        <SummaryBody summary={load.summary} />
      )}
    </section>
  );
}
