import { useState } from "react";

import type { TurnRunIdentity } from "./turnRunIdentityParse";
import {
  presentEndReason,
  presentEndReasonLabel,
  presentRunIdentityKind,
  presentRunState,
  shortRunId,
} from "./turnRunIdentityPresentation";

// Run/Attempt identity of one turn inside the execution details section.
// Only the parsed, allow-listed identity is rendered.

function CopyRunId({ runId }: { runId: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(runId);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };
  return (
    <span className="turn-run-identity__id">
      <code title={runId}>{shortRunId(runId)}</code>
      <button
        type="button"
        className="turn-exec-card__action"
        onClick={copy}
        aria-label="Copy run id"
      >
        {copied ? "Copied" : "Copy"}
      </button>
    </span>
  );
}

export function TurnRunIdentityRow({
  identity,
}: {
  identity: TurnRunIdentity;
}) {
  const kindLabel = presentRunIdentityKind(identity.kind);
  if (identity.kind !== "product_run") {
    return (
      <dl className="turn-exec-details__grid" data-run-kind={identity.kind}>
        <div className="turn-exec-details__field">
          <dt>Run</dt>
          <dd>{kindLabel}</dd>
        </div>
      </dl>
    );
  }
  const { attempt } = identity;
  const state = presentRunState(attempt.state);
  const endReason = presentEndReasonLabel(attempt.endReason);
  const endReasonCode = presentEndReason(attempt.endReason);
  return (
    <dl className="turn-exec-details__grid" data-run-kind={identity.kind}>
      <div className="turn-exec-details__field">
        <dt>Run</dt>
        <dd>{kindLabel}</dd>
      </div>
      <div className="turn-exec-details__field">
        <dt>Run id</dt>
        <dd>
          <CopyRunId runId={identity.runId} />
        </dd>
      </div>
      <div className="turn-exec-details__field">
        <dt>Attempt</dt>
        <dd>#{attempt.number}</dd>
      </div>
      <div className="turn-exec-details__field">
        <dt>Attempt state</dt>
        <dd>
          <span
            className={`turn-run-identity__state turn-run-identity__state--${state.tone}`}
            data-run-tone={state.tone}
          >
            {state.label}
          </span>
        </dd>
      </div>
      <div className="turn-exec-details__field">
        <dt>End reason</dt>
        <dd title={endReasonCode ?? undefined}>{endReason ?? "—"}</dd>
      </div>
    </dl>
  );
}
