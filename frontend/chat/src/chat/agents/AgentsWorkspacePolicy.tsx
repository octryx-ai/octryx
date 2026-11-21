import { useEffect, useState } from "react";

import { loadWorkspacePolicySummary } from "../../admin/components/dataClassification/dataClassificationApi";
import { policyLoadErrorText, readWorkspacePolicy, seatText, sourceWords } from "./workspacePolicyModel";
import type { ToolRuleLine, WorkspacePolicy } from "./workspacePolicyModel";
import { WorkspacePlatformPolicies } from "./WorkspacePlatformPolicies";
import "../../admin/components/dataClassification/dataClassification.css";

const Unstated = ({ what }: { what: string }) => <p className="admin-panel__hint">The server did not state {what}.</p>;

function RuleList({ lines, testId }: { lines: ToolRuleLine[]; testId: string }) {
  return (
    <ul className="workspace-classification__lines" data-testid={testId}>
      {lines.map((line) => <li key={line.id}><code>{line.subject}</code> {line.text}</li>)}
    </ul>
  );
}

// Agents → Governance → "Policy": everything that governs agents in this Workspace on one read-only page —
// the classification and its rules, seat, models, budgets, the agent gateway's tool rules and the connectors.
// Platform admins (the server's `can_edit`) get links to the classification policy matrix, to Limits & budgets and
// to the platform policies that apply here.
export function AgentsWorkspacePolicy({ projectId, onOpenAdminTab }: {
  projectId: string;
  onOpenAdminTab?: (tab: "classificationPolicy" | "runtimeLimits" | "cedarPolicies" | "policyTestBench") => void;
}) {
  const [policy, setPolicy] = useState<WorkspacePolicy | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    setPolicy(null);
    setProblem(null);
    loadWorkspacePolicySummary(projectId)
      .then((payload) => {
        if (!current) return;
        const read = readWorkspacePolicy(payload);
        setPolicy(read);
        if (!read) setProblem("The server's answer was not a Workspace policy.");
      })
      .catch((error) => { if (current) setProblem(policyLoadErrorText(error)); });
    return () => { current = false; };
  }, [projectId]);

  if (problem) return <p className="work-area__error" role="alert" data-testid="workspace-policy-error">{problem}</p>;
  if (!policy) return <p className="agents-area__hint" role="status">Loading the Workspace policy…</p>;

  const source = sourceWords(policy.classificationSource);
  const adminLink = policy.canEdit ? onOpenAdminTab : undefined;
  return (
    <div className="workspace-policy" data-testid="workspace-policy">
      <section className="admin-panel__card workspace-classification" aria-label="Classification" data-testid="workspace-policy-classification">
        <div className="admin-panel__section-header">
          <div>
            <span>Classification: {policy.classification ?? "not set"}</span>
            {source ? <p className="admin-panel__hint">Source: {source}</p> : null}
          </div>
          {adminLink ? (
            <button type="button" className="admin-panel__action-btn" data-testid="workspace-policy-open-matrix" onClick={() => adminLink("classificationPolicy")}>
              Open the classification policy
            </button>
          ) : null}
        </div>
        {policy.matrixInvalid ? (
          <p className="workspace-classification__message" role="alert" data-testid="workspace-policy-matrix-invalid">
            The classification policy could not be read: every level is locked down until a platform admin fixes it.
          </p>
        ) : null}
        {!policy.classification ? (
          <p className="security-field-hint--attention" data-testid="workspace-policy-unclassified">
            No classification is set, so no level's rules apply: seat sessions are refused and Knowledge runs without the reranker and remote embeddings.
          </p>
        ) : policy.rules.length ? (
          <ul className="workspace-classification__lines" data-testid="workspace-policy-rules">
            {policy.rules.map((line) => (
              <li key={line.key} data-allowed={line.allowed === null ? undefined : line.allowed ? "yes" : "no"}>
                {line.allowed === null ? <span className="workspace-classification__mark workspace-classification__mark--pending" aria-hidden="true">·</span>
                  : <span className={`workspace-classification__mark workspace-classification__mark--${line.allowed ? "yes" : "no"}`} aria-hidden="true">{line.allowed ? "✓" : "✗"}</span>}
                {line.label}: {line.value}
              </li>
            ))}
          </ul>
        ) : <Unstated what="the rules of this level" />}
        <p className="admin-panel__hint" data-testid="workspace-policy-seat">{seatText(policy.seat)}</p>
      </section>

      <WorkspacePlatformPolicies workspaceId={projectId} policies={policy.platformPolicies} onOpenAdminTab={adminLink} />

      <section className="admin-panel__card workspace-classification" aria-label="Models and budgets">
        <span className="workspace-classification__heading">Allowed company models</span>
        {policy.models === null ? <Unstated what="the allowed models" />
          : <p className="admin-panel__hint" data-testid="workspace-policy-models">{policy.models.length ? policy.models.join(", ") : "No company model is allowed here."}</p>}
        {policy.deniedModels.length ? (
          <ul className="workspace-classification__lines" data-testid="workspace-policy-denied-models">
            {policy.deniedModels.map((entry) => (
              <li key={entry.alias}>
                <span className="workspace-classification__mark workspace-classification__mark--no" aria-hidden="true">✗</span>
                {entry.alias} not allowed here{entry.reason ? ` (${entry.reason})` : ""}
              </li>
            ))}
          </ul>
        ) : null}
        <div className="admin-panel__section-header">
          <span className="workspace-classification__heading">Budgets</span>
          {adminLink ? (
            <button type="button" className="admin-panel__action-btn" data-testid="workspace-policy-open-limits" onClick={() => adminLink("runtimeLimits")}>
              Limits &amp; budgets
            </button>
          ) : null}
        </div>
        {policy.budgets === null ? <Unstated what="the budgets" /> : policy.budgets.length ? (
          <ul className="workspace-classification__lines" data-testid="workspace-policy-budgets">
            {policy.budgets.map((line) => <li key={line.key}>{line.label}: {line.value}{line.source ? ` (${line.source})` : ""}</li>)}
          </ul>
        ) : <p className="admin-panel__hint">No budget is set.</p>}
      </section>

      <section className="admin-panel__card workspace-classification" aria-label="Tool rules">
        <span className="workspace-classification__heading">Tool rules for agent clients</span>
        {policy.gateway && !policy.gateway.ok ? (
          <p className="workspace-classification__message" role="alert" data-testid="workspace-policy-gateway-invalid">
            The agent gateway policy of this Workspace needs configuration ({policy.gateway.reason ?? "policy_invalid"}), so no tool rule can be shown.
          </p>
        ) : policy.gateway?.source ? <p className="admin-panel__hint" data-testid="workspace-policy-gateway-source">Source: {sourceWords(policy.gateway.source)}</p> : null}
        {policy.toolRules === null ? <Unstated what="the tool rules" />
          : policy.toolRules.length ? <RuleList lines={policy.toolRules} testId="workspace-policy-tool-rules" />
            : <p className="admin-panel__hint">No tool rule is set.</p>}
        {policy.clientPermissions.length ? <RuleList lines={policy.clientPermissions} testId="workspace-policy-permissions" /> : null}
      </section>

      <section className="admin-panel__card workspace-classification" aria-label="Connectors">
        <span className="workspace-classification__heading">Connectors</span>
        {policy.connectors === null ? <Unstated what="the connectors" /> : (
          <ul className="workspace-classification__lines" data-testid="workspace-policy-connectors">
            {policy.connectors.map((line) => <li key={line.family}>{line.label}: {line.mode}</li>)}
          </ul>
        )}
      </section>
    </div>
  );
}
