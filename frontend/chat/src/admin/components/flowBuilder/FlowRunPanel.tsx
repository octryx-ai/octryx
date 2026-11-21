import { useEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import type { FlowValidationReport } from "./flowBuilderTypes";
import { readinessLabel, type FlowNextAction } from "./flowNextAction";
import { validationStatusText, type FlowValidationState } from "./flowValidationFeedback";
import "./flowRunPanel.css";

type FlowRunPanelProps = {
  heading: string;
  nextAction: FlowNextAction;
  running: boolean;
  report: Pick<FlowValidationReport, "valid" | "errors" | "warnings">;
  testCaseCount: number;
  // Id of the shown run; once a run exists the result comes first and the input collapses.
  runKey?: string | null;
  input: ReactNode;
  result: ReactNode;
  readiness: ReactNode;
  quality: ReactNode;
  testCases: ReactNode;
  onRun: () => void;
  onClose: () => void;
  // An explicit Validate: each new key expands Readiness and scrolls it into view.
  revealReadinessKey?: number;
  validationState?: FlowValidationState;
};

/** Readiness starts open after an explicit Validate; each new key opens it again and scrolls it into view. */
function useReadinessReveal(revealReadinessKey: number) {
  const readinessRef = useRef<HTMLDetailsElement>(null);
  const [readinessOpen, setReadinessOpen] = useState(revealReadinessKey > 0);
  useEffect(() => {
    if (!revealReadinessKey) return;
    setReadinessOpen(true);
    // Brought into view, not focused: the result is announced by its status line.
    readinessRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [revealReadinessKey]);
  return { readinessRef, readinessOpen, setReadinessOpen };
}

function FlowRunHeader({ title, onClose }: { title: string; onClose: () => void }) {
  return (
    <div className="flow-builder__operations-header">
      <div>
        <span className="admin-panel__eyebrow">Run &amp; results</span>
        <strong>{title}</strong>
      </div>
      <button type="button" onClick={onClose} aria-label="Close run and results">
        Close
      </button>
    </div>
  );
}

/** Readiness: the validation status line while it has one, then the readiness details. */
function FlowReadinessSection({ detailsRef, open, setOpen, label, validationState, validationStatus, readiness }: {
  detailsRef: RefObject<HTMLDetailsElement>;
  open: boolean;
  setOpen: (open: boolean) => void;
  label: string;
  validationState: FlowValidationState;
  validationStatus: string | null;
  readiness: ReactNode;
}) {
  return (
    <details
      ref={detailsRef}
      className="flow-run-panel__section"
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>Readiness · {label}</summary>
      {validationStatus ? (
        <p className={`flow-run-panel__validation flow-run-panel__validation--${validationState}`} role="status" aria-live="polite">
          {validationStatus}
        </p>
      ) : null}
      {readiness}
    </details>
  );
}

function FlowRunRow({ onRun, disabled, label }: { onRun: () => void; disabled: boolean; label: string }) {
  return (
    <div className="flow-run-panel__run-row">
      <button
        type="button"
        className="admin-panel__button admin-panel__button--primary"
        onClick={onRun}
        disabled={disabled}
      >
        {label}
      </button>
    </div>
  );
}

function FlowRunResult({ title, result }: { title: string; result: ReactNode }) {
  return (
    <section className="flow-run-panel__result" aria-label={title}>
      <span className="admin-panel__section-title">{title}</span>
      {result}
    </section>
  );
}

// Run & results as one readable column. Before a run: next action, test input, Run, result
// placeholder. After a run: the result first, then "Edit input and run again" (collapsed).
// Readiness, quality and test cases are always secondary sections.
export function FlowRunPanel({
  heading, nextAction, running, report, testCaseCount, runKey = null, input, result, readiness, quality, testCases, onRun, onClose,
  revealReadinessKey = 0, validationState = "idle",
}: FlowRunPanelProps) {
  const { readinessRef, readinessOpen, setReadinessOpen } = useReadinessReveal(revealReadinessKey);
  const validationStatus = validationStatusText(validationState, report);
  const runRow = (
    <FlowRunRow onRun={onRun} disabled={running || !nextAction.canRun}
      label={running ? "Running…" : runKey ? "Run again" : "Run this revision"} />
  );
  // While a new run is in flight the shown result belongs to the previous run and says so.
  const resultTitle = running && runKey ? "Previous result (before this run)" : "Result";
  const resultSection = <FlowRunResult title={resultTitle} result={result} />;
  return (
    <section className="flow-builder__operations flow-run-panel" aria-label="Run and results">
      <FlowRunHeader title={running ? "Running this revision…" : heading} onClose={onClose} />
      <div className="flow-run-panel__body">
        {runKey ? resultSection : null}
        <div className={`flow-run-panel__next flow-run-panel__next--${nextAction.canRun ? "ready" : "blocked"}`} role="status">
          <strong>{nextAction.canRun ? "Ready to run" : nextAction.title}</strong>
          <p>{nextAction.detail}</p>
        </div>
        {runKey ? (
          <details key={runKey} className="flow-run-panel__section flow-run-panel__rerun">
            <summary>Edit input and run again</summary>
            {input}
            {runRow}
          </details>
        ) : (
          <>
            {input}
            {runRow}
            {resultSection}
          </>
        )}
        <FlowReadinessSection detailsRef={readinessRef} open={readinessOpen} setOpen={setReadinessOpen}
          label={validationState === "validating" ? "validating…" : readinessLabel(report)} validationState={validationState}
          validationStatus={validationStatus} readiness={readiness} />
        <details className="flow-run-panel__section">
          <summary>Quality</summary>
          {quality}
        </details>
        <details className="flow-run-panel__section">
          <summary>Test cases · {testCaseCount}</summary>
          {testCases}
        </details>
      </div>
    </section>
  );
}
