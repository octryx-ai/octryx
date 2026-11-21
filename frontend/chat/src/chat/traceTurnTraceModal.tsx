import { useEffect, useRef } from "react";
import type { TurnTrace } from "../chatThreadTypes";
import { extractWithinTurnWorkingSummary } from "./traceTurnDiff";
import { TraceValue } from "./traceUiComponents";
import { TraceCallsSection } from "./traceCallsSection";
import { TraceDecisionTimeline } from "./traceDecisionTimeline";
import { TraceTurnDiffSection } from "./traceTurnDiffUi";
import { TraceRawSections, TraceUsageTiles, TraceWorkingSetTiles } from "./traceTurnTraceUsage";
import { TraceWorkflowRoutingPanel } from "./traceWorkflowRoutingPanel";
import { TurnExecutionDetailsSection } from "./run/TurnExecutionDetailsSection";
import type { TurnExecutionSummaryLoad } from "./run/turnExecutionSummary.types";

type TurnTraceModalProps = {
  trace: TurnTrace;
  open: boolean;
  onClose: () => void;
  executionSummary?: TurnExecutionSummaryLoad;
  onRetryExecutionSummary?: () => void;
  /** Loads one call of the turn (GET /chat/api/turn-traces/{id}) when the person opens it. */
  loadTrace?: (traceId: string) => Promise<TurnTrace | null>;
};

// Escape closes the trace like every other dialog.
function useEscapeToClose(open: boolean, onClose: () => void) {
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !event.defaultPrevented) {
        event.preventDefault();
        closeRef.current();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);
}

function TraceModalBody({ trace, executionSummary, onRetryExecutionSummary, loadTrace }: TurnTraceModalProps) {
  const workingSetSummary = extractWithinTurnWorkingSummary(trace);
  const turnDiff =
    (trace.contextSnapshot?.turn_diff as Record<string, unknown> | undefined) ??
    null;
  return (
    <div className="turn-trace-modal__stack">
      {executionSummary ? (
        <TurnExecutionDetailsSection
          load={executionSummary}
          onRetry={onRetryExecutionSummary}
        />
      ) : null}
      <TraceUsageTiles trace={trace} />
      <TraceWorkingSetTiles trace={trace} />
      <TraceCallsSection trace={trace} loadTrace={loadTrace} />
      {workingSetSummary ? (
        <section className="turn-trace-section">
          <h4>Within-Execution Summary</h4>
          <TraceValue value={workingSetSummary} />
        </section>
      ) : null}
      <TraceWorkflowRoutingPanel trace={trace} />
      <TraceDecisionTimeline trace={trace} />
      <TraceTurnDiffSection
        turnDiff={turnDiff}
        className="trace-turn-diff turn-trace-modal__diff"
        keyPrefix="trace-modal"
      />
      <TraceRawSections trace={trace} />
    </div>
  );
}

export function TurnTraceModal(props: TurnTraceModalProps) {
  const { trace, open, onClose } = props;
  useEscapeToClose(open, onClose);
  if (!open) {
    return null;
  }
  return (
    <div className="admin-modal-backdrop" onClick={onClose}>
      <div
        className="admin-panel admin-modal turn-trace-modal"
        role="dialog"
        aria-modal="true"
        aria-label="Execution trace"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="admin-panel__header">
          <div className="admin-panel__header-copy">
            <div className="admin-panel__title">
              {trace.provider && trace.model
                ? `${trace.provider} / ${trace.model}`
                : trace.model || "Model runtime trace"}
            </div>
            <div className="admin-modal__eyebrow">Execution trace</div>
          </div>
          <button
            type="button"
            className="admin-panel__icon-btn"
            onClick={onClose}
            aria-label="Close execution trace"
          >
            <span aria-hidden="true">×</span>
          </button>
        </div>
        <div className="admin-modal__body">
          <TraceModalBody {...props} />
        </div>
      </div>
    </div>
  );
}
