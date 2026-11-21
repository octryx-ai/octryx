// Tool event detail blocks: the execution event (command, exit code, output sizes) and the evidence contract.

import type { ToolEvent } from "../chatThreadTypes";
import { extractExecutionEvent } from "./traceToolEventValues";

function valueLabel(value: unknown) {
  if (Array.isArray(value)) {
    return value.map((item) => String(item)).join(" ");
  }
  return String(value ?? "").trim();
}

export function ExecutionEventSummary({ event }: { event: ToolEvent }) {
  const executionEvent = extractExecutionEvent(event);
  if (!executionEvent) {
    return null;
  }
  const kind = valueLabel(executionEvent.kind);
  const status = valueLabel(executionEvent.status);
  const command = valueLabel(executionEvent.command);
  const cwd = valueLabel(executionEvent.cwd);
  const exitCode =
    typeof executionEvent.exit_code === "number"
      ? String(executionEvent.exit_code)
      : "";
  const stdoutChars =
    typeof executionEvent.stdout_chars === "number"
      ? `${executionEvent.stdout_chars} stdout chars`
      : "";
  const stderrChars =
    typeof executionEvent.stderr_chars === "number"
      ? `${executionEvent.stderr_chars} stderr chars`
      : "";
  return (
    <div className="tool-execution-event">
      <div className="tool-execution-event__header">
        <span>{[kind, status].filter(Boolean).join(" · ") || "Execution"}</span>
        {exitCode ? <span>exit {exitCode}</span> : null}
      </div>
      <div className="tool-execution-event__meta">
        {cwd ? <span>{cwd}</span> : null}
        {stdoutChars ? <span>{stdoutChars}</span> : null}
        {stderrChars ? <span>{stderrChars}</span> : null}
      </div>
      {command ? <code>{command}</code> : null}
    </div>
  );
}

export function EvidenceContractSummary({
  contract,
}: {
  contract: Record<string, unknown> | null;
}) {
  if (!contract) {
    return null;
  }
  const status = String(contract.status || "").trim().toLowerCase();
  const state = String(contract.evidence_state || "").trim();
  const strategy = String(contract.strategy || "").trim();
  const hardCapped = Boolean(contract.hard_capped);
  const missingPaths = Array.isArray(contract.missing_paths)
    ? contract.missing_paths.map((item) => String(item)).filter(Boolean)
    : [];
  const requiredCount = Array.isArray(contract.required_paths)
    ? contract.required_paths.length
    : 0;
  const isPassed = status === "passed";
  return (
    <div
      className={`tool-evidence-contract tool-evidence-contract--${
        isPassed ? "passed" : "failed"
      }`}
    >
      <div className="tool-evidence-contract__header">
        <span className="tool-evidence-contract__title">
          Evidence contract
        </span>
        <span className="tool-evidence-contract__status">
          {isPassed ? "Compact evidence" : "Incomplete evidence"}
        </span>
      </div>
      <div className="tool-evidence-contract__meta">
        {strategy ? <span>{strategy}</span> : null}
        {state ? <span>{state}</span> : null}
        {requiredCount ? <span>{requiredCount} required fields</span> : null}
        {hardCapped ? <span>hard capped</span> : null}
      </div>
      {missingPaths.length ? (
        <div className="tool-evidence-contract__missing">
          Missing: {missingPaths.slice(0, 6).join(", ")}
          {missingPaths.length > 6 ? ` +${missingPaths.length - 6}` : ""}
        </div>
      ) : null}
    </div>
  );
}
