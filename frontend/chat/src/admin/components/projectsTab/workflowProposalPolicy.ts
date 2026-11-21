// The Workspace switch `workflow_proposal_policy` as explicit states.
// Server contract: the stored section is `{"enabled": bool}` or `{}`; only an explicit `false` turns proposals off, and
// `{"enabled": null}` in a merge patch resets the section to the default (on).

export const WORKFLOW_PROPOSAL_POLICY_KEY = "workflow_proposal_policy";

export type WorkflowProposalPolicyState = "default" | "enabled" | "disabled";

export const WORKFLOW_PROPOSAL_POLICY_STATES: ReadonlyArray<{
  state: WorkflowProposalPolicyState;
  label: string;
  stored: string;
  description: string;
}> = [
  {
    state: "default",
    label: "Default (on)",
    stored: "{}",
    description:
      "No explicit value: the platform default applies and proposals are on.",
  },
  {
    state: "enabled",
    label: "On",
    stored: '{"enabled": true}',
    description:
      "A turn without a selected workflow gets one proposal call. A proposed workflow waits for the user to start it (needs_confirmation).",
  },
  {
    state: "disabled",
    label: "Off",
    stored: '{"enabled": false}',
    description:
      "No proposal model call. A turn without a selected workflow runs as a plain chat (status disabled, reason policy_disabled).",
  },
];

export function workflowProposalPolicyState(config: unknown): WorkflowProposalPolicyState {
  const section =
    config && typeof config === "object"
      ? (config as Record<string, unknown>)[WORKFLOW_PROPOSAL_POLICY_KEY]
      : undefined;
  const enabled =
    section && typeof section === "object" ? (section as Record<string, unknown>).enabled : undefined;
  if (enabled === false) return "disabled";
  if (enabled === true) return "enabled";
  return "default";
}

export function workflowProposalPolicyPatch(state: WorkflowProposalPolicyState) {
  const enabled = state === "default" ? null : state === "enabled";
  return { [WORKFLOW_PROPOSAL_POLICY_KEY]: { enabled } };
}
