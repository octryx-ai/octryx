// What a box from the catalog starts with. A draft may be incomplete (the panel says what is missing); only
// publishing needs a valid workflow.
import type { NodeKind } from "../types";

/** The technical name a designer-made agent step carries (the backend requires ``workflow_id`` and
 * ``workflow_class``; a neutral value no routing rule reacts to). Found missing in the */
export const DESIGNER_STEP_ID = "designer_step";

/** What a new role of a Parallel work box runs as: an ordinary agent step that may change code. */
export function roleTemplate(): Record<string, unknown> {
  return { agent: "", workflow_contract: { workflow_id: DESIGNER_STEP_ID, workflow_class: DESIGNER_STEP_ID,
    capability_class: "change", source_steps: [], checks: [] }, tool_policy: { allowlist: [] } };
}

export function defaultConfig(type: NodeKind): Record<string, unknown> {
  switch (type) {
    case "phase":
      return { agent: "", workflow_contract: { workflow_id: DESIGNER_STEP_ID, workflow_class: DESIGNER_STEP_ID,
        capability_class: "read_only", source_steps: [], checks: [] },
        tool_policy: { allowlist: [] } };
    case "gate":
      return { checks: [] };
    case "decision":
      return { source: "", options: [] };
    case "approval":
      return { decider: "requester", title: "", summary: "" };
    case "user_confirmation":
      return { subject: "advance" };
    case "user_conversation":
      return { question: "" };
    case "watch":
      return { conditions: [] };
    case "platform_action":
      return { action: "" };
    case "sub_workflow":
      return { workflow_key: "" };
    case "outcome":
      return { outcome: "done" };
    case "parallel_work":
      return { plan: "", roles: { backend: roleTemplate(), frontend: roleTemplate(), test: roleTemplate() }, parallel: true };
    default:
      return {};
  }
}
