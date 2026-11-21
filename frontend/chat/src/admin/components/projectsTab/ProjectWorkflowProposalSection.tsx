import type { AdminProjectQuality } from "../../types/projectQualityTypes";
import "../governedWrite/governedWrite.css";
import { GovernedIssueList } from "../governedWrite/GovernedIssueList";
import {
  WORKFLOW_PROPOSAL_POLICY_STATES,
  workflowProposalPolicyPatch,
  type WorkflowProposalPolicyState,
} from "./workflowProposalPolicy";
import {
  revokeStandingToolRulePatch,
  standingToolRuleLabel,
  standingToolRules,
  type StandingToolRule,
} from "./standingToolApprovals";

import { useWorkflowProposalPolicy } from "./useWorkflowProposalPolicy";

type Props = {
  ctx: Record<string, unknown>;
};

type Policy = ReturnType<typeof useWorkflowProposalPolicy>;

function ProposalPolicyHeader({ stored, saving, unchanged, save }: {
  stored: WorkflowProposalPolicyState | null;
  saving: boolean;
  unchanged: boolean;
  save: () => Promise<void>;
}) {
  return (
    <div className="admin-panel__section-header">
      <div>
        <span>Workflow proposals</span>
        <p className="admin-panel__hint">
          Saved:{" "}
          <strong data-testid="proposal-policy-stored">{stored ?? "loading"}</strong>
        </p>
      </div>
      <button
        type="button"
        className="admin-panel__action-btn admin-panel__action-btn--primary"
        onClick={() => void save()}
        disabled={saving || stored === null || unchanged}
      >
        {saving ? "Saving..." : "Save proposal policy"}
      </button>
    </div>
  );
}

function ProposalPolicyChoices({ policy }: { policy: Policy }) {
  const { choice, setChoice, stored } = policy;
  return (
    <div className="governed-choices" role="radiogroup" aria-label="Workflow proposal policy">
      {WORKFLOW_PROPOSAL_POLICY_STATES.map((entry) => (
        <label
          key={entry.state}
          className={`governed-choice${
            choice === entry.state ? " governed-choice--selected" : ""
          }`}
        >
          <input
            type="radio"
            name="workflow-proposal-policy"
            value={entry.state}
            checked={choice === entry.state}
            onChange={() => setChoice(entry.state)}
            disabled={stored === null}
          />
          <span className="governed-choice__key">
            {entry.label} <code>{entry.stored}</code>
          </span>
          <span className="governed-choice__text">{entry.description}</span>
        </label>
      ))}
    </div>
  );
}

function StandingToolRuleList({ toolRules, saving, revokeToolRule }: {
  toolRules: StandingToolRule[];
  saving: boolean;
  revokeToolRule: (rule: StandingToolRule) => Promise<void>;
}) {
  return toolRules.length === 0 ? (
    <p className="admin-panel__hint" data-testid="standing-tool-rules-empty">
      No standing tool approvals.
    </p>
  ) : (
    <ul className="admin-panel__list" aria-label="Standing tool approvals">
      {toolRules.map((rule) => (
        <li key={standingToolRuleLabel(rule)}>
          <code>{standingToolRuleLabel(rule)}</code>
          {rule.grantedBy ? ` · granted by ${rule.grantedBy}` : null}
          {rule.grantedAt ? ` · ${rule.grantedAt}` : null}{" "}
          <button
            type="button"
            className="admin-panel__action-btn"
            onClick={() => void revokeToolRule(rule)}
            disabled={saving}
          >
            Revoke
          </button>
        </li>
      ))}
    </ul>
  );
}

// Workspace policy for workflow proposals: the switch, and the standing
// "Always for this Workspace" tool approvals, each revocable here. Admin-only,
// validated and audited by the project config write
// (`admin.project_config.updated`).
export function ProjectWorkflowProposalSection({ ctx }: Props) {
  const project = (ctx as { configuringProjectQuality?: AdminProjectQuality | null })
    .configuringProjectQuality;
  const projectId = project?.id ?? "";
  const policy = useWorkflowProposalPolicy(projectId);
  const { stored, choice, config, issues, saving, notice, write } = policy;

  if (!project) return null;

  const save = () =>
    write(workflowProposalPolicyPatch(choice), "Workflow proposal policy saved.");
  const revokeToolRule = (rule: StandingToolRule) =>
    write(revokeStandingToolRulePatch(config, rule), `Revoked: ${standingToolRuleLabel(rule)}.`);
  const toolRules = standingToolRules(config);
  const unchanged = choice === stored;

  return (
    <section className="admin-panel__stack" aria-label="Workflow proposals">
      <ProposalPolicyHeader stored={stored} saving={saving} unchanged={unchanged} save={save} />
      <section className="admin-panel__card">
        <p className="admin-panel__hint">
          Whether a turn without a selected workflow asks the model to propose one. An explicitly selected
          workflow always wins and never triggers a proposal.
        </p>
        <ProposalPolicyChoices policy={policy} />
        <p className="admin-panel__hint">
          Always for this Workspace on tool approvals: a Workspace admin allowed the tool (and, for commands, the
          command class) from the chat. A matching call runs without asking; execution-policy denies and content
          checks (secrets, content policies) still apply.
        </p>
        <StandingToolRuleList toolRules={toolRules} saving={saving} revokeToolRule={revokeToolRule} />
        <GovernedIssueList issues={issues} label="Proposal policy errors" />
        {notice ? <p className="governed-notice">{notice}</p> : null}
      </section>
    </section>
  );
}
