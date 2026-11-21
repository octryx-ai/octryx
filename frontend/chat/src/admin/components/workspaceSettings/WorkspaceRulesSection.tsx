import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import { readJson } from "../../utils/adminPanelHelpers";
import { useAdminNavigation } from "../../adminNavigation";
import { CommandSafetyWorkspaceDrawer } from "../commandSafety/CommandSafetyPage";
import { ClassificationOverrideDrawer } from "../dataClassification/ClassificationOverrideDrawer";
import { levelLabelOf, matrixRows } from "../dataClassification/classificationMatrixRows";
import { overrideChips } from "../dataClassification/classificationOverridesModel";
import type { Rules } from "../dataClassification/classificationPolicyModel";
import { saveWorkspaceOverrides } from "../dataClassification/dataClassificationApi";
import { LevelTag } from "../settingsKit/SettingsKit";
import "../settingsKit/settingsKit.css";
import { ApprovalPolicyDrawer } from "../toolApprovals/ApprovalPolicyDrawer";
import { workspaceApprovalBody, type ApprovalPolicy } from "../toolApprovals/toolApprovalsModel";
import { workspaceSummary } from "../toolApprovals/toolApprovalsModel";
import { WorkspaceBudgetInputs } from "./WorkspaceBudgetInputs";
import type { WorkspaceRules } from "./workspaceRulesData";
import { loadWorkspaceRules } from "./workspaceRulesData";
import { settingsErrorText, toolVisibilityText } from "./workspaceSettingsModel";

type Drawer = "classification" | "approvals" | "command" | null;

function Row({ rule, effective, declared, action }: { rule: string; effective: ReactNode; declared: ReactNode; action?: ReactNode }) {
  return (
    <tr>
      <td data-label="Rule">{rule}</td>
      <td data-label="This Workspace">{effective}</td>
      <td data-label="Declared in">{declared}</td>
      <td>{action}</td>
    </tr>
  );
}

const Muted = ({ children }: { children: ReactNode }) => <span className="admin-panel__cell--muted">{children}</span>;

const open = (label: string, onClick: () => void, testId?: string) => (
  <button type="button" className="admin-panel__action-btn" data-testid={testId} onClick={onClick}>{label}</button>
);

// Workspace → Rules: everything that limits this Workspace, each with the
// one place it is declared. Classification overrides, tool approvals and command safety open the same drawers as their
// Settings pages; the budget overrides are edited inline.
export function WorkspaceRulesSection({ projectId, projectName, onOpenSection }: {
  projectId: string;
  projectName: string;
  onOpenSection: (section: "connectors" | "coding") => void;
}) {
  const { openAdminTab } = useAdminNavigation();
  const [rules, setRules] = useState<WorkspaceRules | null>(null);
  const [drawer, setDrawer] = useState<Drawer>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const load = useCallback(async () => setRules(await loadWorkspaceRules(projectId)), [projectId]);
  useEffect(() => { void load(); }, [load]);
  const rows = useMemo(() => matrixRows(rules?.classification?.families ?? []), [rules]);

  if (!rules) return <p className="sk-hint" role="status">Loading the rules…</p>;

  const { classification, classified, approvals, commandSafety } = rules;
  const view = rulesView(rules, rows, projectId);
  const { levelInfo, labels, overrides, approvalRow } = view;
  const close = () => { setDrawer(null); setProblem(null); };
  const run = (action: () => Promise<unknown>) => runRuleAction(action, { setBusy, close, load, setProblem });
  const saveApprovals = (mode: "inherit" | "add", policy: ApprovalPolicy) => run(() => readJson<unknown>(
    `/api/v1/admin/tool-approvals/workspaces/${encodeURIComponent(projectId)}`,
    { method: "PUT", body: JSON.stringify(workspaceApprovalBody(mode, policy)) },
  ));
  return (
    <div className="sk-wsec" data-testid="workspace-rules">
      <p className="sk-hint">Everything that limits this Workspace, each with the one place it is declared.</p>
      <RulesTable rules={rules} projectId={projectId} view={view} setDrawer={setDrawer} openAdminTab={openAdminTab}
        onOpenSection={onOpenSection} />

      {drawer === "classification" && classified?.level && classification ? (
        <ClassificationOverrideDrawer name={projectName} levelLabel={levelLabelOf(classified.level, labels)}
          levelRules={levelInfo?.rules} rows={rows} overrides={overrides} busy={busy} problem={problem} onClose={close}
          onSave={(next) => void run(() => saveWorkspaceOverrides(projectId, next))} />
      ) : null}
      {drawer === "approvals" && approvals && approvalRow ? (
        <ApprovalPolicyDrawer title={projectName} workspace mode={approvalRow.mode} policy={approvalRow.own} defaults={approvals.defaults}
          risks={approvals.risks} tools={approvals.tools} busy={busy} problem={problem} onClose={close}
          onSave={(mode, policy) => void saveApprovals(mode, policy)} />
      ) : null}
      {drawer === "command" && commandSafety ? (
        <CommandSafetyWorkspaceDrawer workspace={{ id: projectId, name: projectName }} platform={commandSafety} onClose={close}
          onSaved={() => { close(); void load(); }} />
      ) : null}
    </div>
  );
}

// What the rows show, worked out from the loaded rules once per render.
function rulesView(rules: WorkspaceRules, rows: ReturnType<typeof matrixRows>, projectId: string) {
  const { classification, classified, approvals, commandSafety, mcp } = rules;
  const overrides = (classified?.overrides ?? {}) as Rules;
  return {
    levelInfo: classification?.levels.find((level) => level.level === classified?.level),
    labels: Object.fromEntries((classification?.levels ?? []).map((level) => [level.level, level.label])),
    overrides,
    chips: overrideChips(rows, overrides).length,
    approvalRow: approvals?.workspaces.find((row) => row.id === projectId) ?? null,
    commandRow: commandSafety?.workspaces.find((row) => row.id === projectId) ?? null,
    allowedServers: mcp?.filter((server) => server.allowed).map((server) => server.name) ?? null,
  };
}

// A drawer's save: busy while it runs; on success the drawer closes and the rules reload, else the problem shows.
async function runRuleAction(action: () => Promise<unknown>, steps: {
  setBusy: (busy: boolean) => void;
  close: () => void;
  load: () => Promise<void>;
  setProblem: (problem: string | null) => void;
}) {
  steps.setBusy(true);
  try {
    await action();
    steps.close();
    await steps.load();
  } catch (error) {
    steps.setProblem(settingsErrorText(error));
  } finally {
    steps.setBusy(false);
  }
}

// One row per rule: what applies to this Workspace, where it is declared, and the action that edits or opens it.
function RulesTable({ rules, projectId, view, setDrawer, openAdminTab, onOpenSection }: {
  rules: WorkspaceRules;
  projectId: string;
  view: ReturnType<typeof rulesView>;
  setDrawer: (drawer: Drawer) => void;
  openAdminTab: ReturnType<typeof useAdminNavigation>["openAdminTab"];
  onOpenSection: (section: "connectors" | "coding") => void;
}) {
  const { labels, levelInfo, chips, approvalRow, commandRow, allowedServers } = view;
  const { classification, classified, coding, tools } = rules;
  return (
    <table className="admin-panel__table sk-cards">
      <thead><tr><th>Rule</th><th>This Workspace</th><th>Declared in</th><th /></tr></thead>
      <tbody>
        <Row rule="Classification"
          effective={classified?.level ? (
            <span className="sk-lv">
              <LevelTag label={levelLabelOf(classified.level, labels)} color={levelInfo?.info.color} />
              {chips ? ` · ${chips} stricter ${chips === 1 ? "override" : "overrides"}` : ""}
            </span>
          ) : <span className="work-badge work-badge--danger">No level</span>}
          declared="Here (level) · Classification (rules)"
          action={classified?.level && classification ? open("Edit", () => setDrawer("classification"), "rules-classification-edit")
            : open("Open", () => openAdminTab("classificationPolicy"))} />
        <Row rule="Tool approvals" effective={approvalRow ? workspaceSummary(approvalRow) : <Muted>Platform admins only</Muted>}
          declared="Tool & approval policies"
          action={approvalRow ? open("Edit", () => setDrawer("approvals"), "rules-approvals-edit") : open("Open", () => openAdminTab("policies"))} />
        <Row rule="MCP servers" effective={allowedServers === null ? <Muted>–</Muted> : allowedServers.length ? allowedServers.join(", ") : "None"}
          declared="Connectors (this Workspace)" action={open("Open", () => onOpenSection("connectors"))} />
        <Row rule="Tools (visibility)"
          effective={tools ? <span data-testid="rules-tools">{toolVisibilityText(tools)}</span> : <Muted>–</Muted>}
          declared={tools?.source === "runtime_policy.tool_policy" ? "Workspace tool policy (runtime copy) · read-only"
            : "Workspace tool policy · read-only"} />
        <Row rule="Command safety" effective={commandRow ? (commandRow.mode === "override" ? "Own values" : "Inherit platform") : <Muted>Platform admins only</Muted>}
          declared="Command safety"
          action={commandRow ? open("Edit", () => setDrawer("command"), "rules-command-edit") : open("Open", () => openAdminTab("commandSafety"))} />
        <Row rule="Forbidden actions"
          effective={coding ? `${coding.toolRules.length} command & file ${coding.toolRules.length === 1 ? "rule" : "rules"} + platform policies` : <Muted>–</Muted>}
          declared="Coding tools & devices · Policies"
          action={(
            <span className="sk-row">
              {open("Rules", () => onOpenSection("coding"))}
              {open("Policies", () => openAdminTab("cedarPolicies"))}
            </span>
          )} />
        <Row rule="Budget" effective={<WorkspaceBudgetInputs projectId={projectId} />}
          declared={<>Here (overrides) · platform:{" "}
            <button type="button" className="sk-link" onClick={() => openAdminTab("runtimeLimits")}>Limits &amp; budgets</button></>} />
        <Row rule="Who approves" effective="The platform approval rule" declared="Approval rule" action={open("Open", () => openAdminTab("approvalRule"))} />
      </tbody>
    </table>
  );
}
