import { PolicySentence } from "../../admin/components/policyEngine/PolicySentence";
import { writePolicyFilter } from "../../admin/components/policyEngine/policyLinks";
import type { PlatformPolicyLine } from "./workspacePolicyModel";
import "../../admin/components/policyEngine/policiesPage.css";

type PolicyTab = "cedarPolicies" | "policyTestBench";

// Agents → Governance → Policy, "Platform policies for this Workspace": the published custom
// policies that can block agents here, as sentences. Platform admins get "Open in Policies" (the list filtered by
// this Workspace) and "Test a request" (the test bench).
export function WorkspacePlatformPolicies({ workspaceId, policies, onOpenAdminTab }: {
  workspaceId: string;
  policies: PlatformPolicyLine[] | null;
  onOpenAdminTab?: (tab: PolicyTab) => void;
}) {
  if (policies === null) return null;
  return (
    <section className="admin-panel__card workspace-classification" aria-label="Platform policies" data-testid="workspace-platform-policies">
      <div className="admin-panel__section-header">
        <span>Platform policies for this Workspace</span>
        <span className="work-badge work-badge--neutral" data-testid="workspace-platform-policies-count">{policies.length} apply</span>
      </div>
      <p className="admin-panel__hint">Custom policies published by platform admins that can block agents in this Workspace.</p>
      {policies.length ? policies.map((item) => (
        <div key={item.id} className="policies__summary" data-testid="workspace-platform-policy">
          ● <PolicySentence segments={item.sentence} className="policies__summary" />
          {item.source === "hand_written" ? <> <span className="work-badge work-badge--neutral">Hand-written</span></> : null}
        </div>
      )) : <p className="admin-panel__hint" data-testid="workspace-platform-policies-none">No platform policy blocks anything here.</p>}
      {onOpenAdminTab ? (
        <div className="policies__row">
          <button type="button" className="admin-panel__action-btn" data-testid="workspace-platform-policies-open"
            onClick={() => { writePolicyFilter({ workspace: workspaceId }); onOpenAdminTab("cedarPolicies"); }}>Open in Policies →</button>
          <button type="button" className="admin-panel__action-btn" data-testid="workspace-platform-policies-test"
            onClick={() => onOpenAdminTab("policyTestBench")}>Test a request</button>
        </div>
      ) : null}
    </section>
  );
}
