// The one "next required action" of the workflow editor. The Run buttons (header and Run &
// results panel) and the panel's guidance all read this, so they cannot disagree with the
// validation report or the saved/unsaved state.
import type { FlowDefinitionVersion, FlowValidationReport } from "./flowBuilderTypes";

export type FlowNextActionKind =
  | "create"
  | "select_revision"
  | "save"
  | "archived"
  | "add_step"
  | "fix_errors"
  | "validate"
  | "running"
  | "run";

export type FlowNextAction = {
  kind: FlowNextActionKind;
  title: string;
  detail: string;
  canRun: boolean;
};

export type FlowNextActionInput = {
  hasFlow: boolean;
  flowArchived: boolean;
  version: Pick<FlowDefinitionVersion, "version" | "status"> | undefined;
  dirty: boolean;
  report: Pick<FlowValidationReport, "valid" | "errors">;
  nodeCount: number;
  running: boolean;
};

function blocked(kind: FlowNextActionKind, title: string, detail: string): FlowNextAction {
  return { kind, title, detail, canRun: false };
}

export function flowNextAction(input: FlowNextActionInput): FlowNextAction {
  const { version, report } = input;
  if (!input.hasFlow) {
    return blocked("create", "Create the draft first", "Run uses a saved revision. Create the draft to run it.");
  }
  if (!version) {
    return blocked("select_revision", "Select a saved revision", "This revision is no longer available. Open one from Versions.");
  }
  if (input.dirty) {
    return blocked("save", "Save the draft first", "You have unsaved changes. Run uses the saved revision, so save the draft before running.");
  }
  if (input.flowArchived || version.status === "archived") {
    return blocked("archived", "Archived revisions cannot run", "Open a draft or published revision to run this workflow.");
  }
  if (input.nodeCount === 0) {
    return blocked("add_step", "Add a step first", "This revision has no steps to run.");
  }
  const errorCount = report.errors?.length ?? 0;
  if (errorCount > 0) {
    const noun = errorCount === 1 ? "error" : "errors";
    return blocked("fix_errors", `Fix ${errorCount} validation ${noun}`, "Readiness lists each error; select one to jump to its step. Then save the draft.");
  }
  if (!report.valid) {
    return blocked("validate", "Validate this revision", "This revision has no passing validation result yet. Use Validate in the header.");
  }
  if (input.running) {
    return blocked("running", "Running this revision…", `Revision ${version.version} is running.`);
  }
  return {
    kind: "run",
    title: "Run this revision",
    detail: `Runs saved revision ${version.version} (${version.status}) exactly as stored.`,
    canRun: true,
  };
}

// Short label for the Readiness section header, consistent with the next action.
export function readinessLabel(report: Pick<FlowValidationReport, "valid" | "errors" | "warnings">): string {
  const errors = report.errors?.length ?? 0;
  if (errors) return `${errors} error${errors === 1 ? "" : "s"}`;
  if (!report.valid) return "not validated";
  const warnings = report.warnings?.length ?? 0;
  return warnings ? `valid · ${warnings} warning${warnings === 1 ? "" : "s"}` : "valid";
}
