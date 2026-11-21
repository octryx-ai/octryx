// Feedback for an explicit "Validate" in the workflow editor.
//
// An explicit Validate opens Run & results with Readiness expanded and says what is happening:
// validating, the result (blocking errors, warnings, passed) or that the request failed. Validation
// that runs as part of another operation (a run refreshing a stale "Ready to run") never opens or
// moves anything. A response only applies while the editor still shows the flow, revision and
// definition it validated; a stale answer never replaces the current report.
import { useCallback, useRef, useState } from "react";
import type { FlowValidationReport } from "./flowBuilderTypes";

export type FlowValidationTarget = {
  flowId: string | null;
  versionId: string | null;
  definitionJson: string;
};
export type FlowValidationState = "idle" | "validating" | "done" | "failed";
export type FlowValidationRequest = {
  sequence: number;
  target: FlowValidationTarget;
  explicit: boolean;
};

export function sameValidationTarget(
  a: FlowValidationTarget,
  b: FlowValidationTarget,
): boolean {
  return (
    a.flowId === b.flowId &&
    a.versionId === b.versionId &&
    a.definitionJson === b.definitionJson
  );
}

const revisionKey = (target: FlowValidationTarget) =>
  `${target.flowId ?? ""}:${target.versionId ?? ""}`;

export function validationStatusText(
  state: FlowValidationState,
  report: Pick<FlowValidationReport, "valid" | "errors" | "warnings">,
): string | null {
  if (state === "idle") return null;
  if (state === "validating") return "Validating the current draft…";
  if (state === "failed")
    return "Validation did not finish. See the message above, then validate again.";
  const errors = report.errors?.length ?? 0;
  const warnings = report.warnings?.length ?? 0;
  if (errors) {
    return `Validation found ${errors} blocking error${errors === 1 ? "" : "s"}. Select one to open its step.`;
  }
  if (!report.valid)
    return "Validation did not return a result. Validate again.";
  return warnings
    ? `Validation passed with ${warnings} warning${warnings === 1 ? "" : "s"}.`
    : "Validation passed.";
}

// The step a validation issue names: an edge "a->b" names its source, "node.config" its node, and a
// message that starts with "node-id:" names that node. Only ids that exist in the definition match.
export function validationIssueNodeId(
  message: string,
  nodeIds: readonly string[],
): string | null {
  const known = new Set(nodeIds);
  const candidates = [
    message.match(/([A-Za-z0-9_-]+)->([A-Za-z0-9_-]+)/)?.[1],
    message.match(/([A-Za-z0-9_-]+)\.(config|input_schema|output_schema)/)?.[1],
    message.match(/^([A-Za-z0-9_-]+):\s/)?.[1],
  ];
  return (
    candidates.find(
      (id): id is string => Boolean(id) && known.has(id as string),
    ) ?? null
  );
}

export function useFlowValidationFeedback(current: FlowValidationTarget) {
  const latest = useRef(current);
  latest.current = current;
  const sequence = useRef(0);
  const [revealKey, setRevealKey] = useState(0);
  const [state, setState] = useState<{
    value: FlowValidationState;
    revision: string;
  }>({ value: "idle", revision: "" });

  const begin = useCallback((explicit: boolean): FlowValidationRequest => {
    sequence.current += 1;
    const request = {
      sequence: sequence.current,
      target: { ...latest.current },
      explicit,
    };
    if (explicit) {
      setState({ value: "validating", revision: revisionKey(request.target) });
      setRevealKey((key) => key + 1);
    }
    return request;
  }, []);
  // Current: no newer validation started and the editor still shows what was validated.
  const isCurrent = useCallback(
    (request: FlowValidationRequest) =>
      request.sequence === sequence.current &&
      sameValidationTarget(request.target, latest.current),
    [],
  );
  const settle = useCallback(
    (request: FlowValidationRequest, outcome: "done" | "failed" | "stale") => {
      if (!request.explicit) return;
      if (outcome === "stale") {
        setState((previous) =>
          previous.revision === revisionKey(request.target)
            ? { ...previous, value: "idle" }
            : previous,
        );
        return;
      }
      setState({ value: outcome, revision: revisionKey(request.target) });
      setRevealKey((key) => key + 1);
    },
    [],
  );
  // A result belongs to the revision it was produced for; another flow or revision shows none.
  const shown: FlowValidationState =
    state.revision === revisionKey(current) ? state.value : "idle";
  return { begin, isCurrent, settle, revealKey, state: shown };
}
