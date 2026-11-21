import type { ReactNode } from "react";

import { ActionMenu } from "../../../admin/components/workflowSurfaces/ActionMenu";
import { ConfirmDialog } from "../../../admin/components/confirm/ConfirmDialog";
import type { ToolRule } from "../../../admin/components/workspaceSettings/workspaceSettingsModel";
import { DataTable, type DataTableColumn } from "../../../layout/DataTable";
import { LoadingState } from "../../../layout/LoadingState";
import { codingRuleRows, ruleText, type CodingRuleRow } from "./codingRulesTable";
import { CodingRulePanel } from "./CodingRulePanel";
import { useCodingEffectiveRules, type CodingRulesProps } from "./useCodingEffectiveRules";
import "./codingRules.css";

// Work › Coding rules: everything that limits the coding agent in one compact table, What / Rule /
// Applies to / Source, in words; a rule listed by more than one source is one row. A row opens the rule in the side
// panel: a Workspace command & file rule is changed there and removed with ⋯, by those who may edit the
// Workspace's rules; any other rule is read only and names its source and the place it is changed. "Add rule" (the
// page's primary action, `adding`) opens the same panel. Everything is saved the way Workspace settings › Coding tools
// & devices saves it (PUT …/coding with the whole rule list).
export function CodingEffectiveRules(props: CodingRulesProps & {
  workspaceName: string;
  adding?: boolean;
  // Whether this person may add a rule (Workspace admins and owners, platform admins).
  onEditableChange?: (editable: boolean) => void;
}) {
  const { adding = false, onAddingChange } = props;
  const page = useCodingEffectiveRules(props);
  const { rules, coding, error, notice, openKey, removing, saving, panelError, setOpenKey, setRemoving, setPanelError, workspaceRule } = page;

  if (error) return <div className="work-area__error" role="alert">{error}</div>;
  if (!rules) return <LoadingState label="the rules" />;
  const rows = codingRuleRows(rules);
  const openRow = rows.find((row) => row.key === openKey) ?? null;
  const openRule = workspaceRule(openRow);
  const taken = coding?.toolRules.map((rule) => rule.id) ?? [];
  const confirmRemove = removing ? (
    <ConfirmDialog title="Remove this rule?" confirmLabel="Remove rule" busy={saving} error={panelError}
      onCancel={() => { setPanelError(null); setRemoving(null); }} onConfirm={() => void page.removeRule(removing)}>
      <p>{`${removing.what}: ${ruleText(removing.rule)}. From the next tool call the coding agent is no longer stopped by it.`}</p>
    </ConfirmDialog>
  ) : null;
  return (
    <div className="coding-rules">
      {notice ? <div className="work-note" role="status">{notice}</div> : null}
      <DataTable label="Coding rules" columns={CODING_RULE_COLUMNS} rows={rows} rowKey={(row) => row.key}
        onOpen={(row) => { setPanelError(null); onAddingChange?.(false); setOpenKey(row.key); }} selectedKey={openKey}
        rowMenu={rows.some((row) => workspaceRule(row)) ? (row) => (workspaceRule(row) ? (
          <ActionMenu row={{ objectName: ruleText(row.rule) }} items={[
            { label: "Edit rule", onSelect: () => { setPanelError(null); setOpenKey(row.key); } },
            { label: "Remove rule", danger: true, onSelect: () => setRemoving(row) },
          ]} />
        ) : null) : undefined}
        testId="coding-rules-table" empty={{ text: "No rule limits the coding agent in this Workspace." }} />
      {/* A confirmation asked from the open panel sits inside it, so Escape closes only the confirmation. */}
      {adding && coding ? (
        <CodingRulePanel key="add" row={null} rule={null} taken={taken} busy={saving} error={panelError} onClose={page.closePanel}
          onSave={(rule) => void page.addRule(rule)} onOpenEditPlace={page.openEdit} />
      ) : openRow ? (
        <OpenRulePanel key={openRow.key} row={openRow} rule={openRule} taken={taken} busy={saving} error={panelError} page={page}>
          {removing ? confirmRemove : null}
        </OpenRulePanel>
      ) : null}
      {removing && !openRow ? confirmRemove : null}
    </div>
  );
}

// The open row's panel: read only, or changed and removed when it is the Workspace's own rule.
function OpenRulePanel({ row, rule, taken, busy, error, page, children }: {
  row: CodingRuleRow; rule: ToolRule | null; taken: string[]; busy: boolean; error: string | null; children: ReactNode;
  page: Pick<ReturnType<typeof useCodingEffectiveRules>, "closePanel" | "openEdit" | "changeRule" | "setRemoving">;
}) {
  return (
    <CodingRulePanel row={row} rule={rule} taken={taken} busy={busy} error={error}
      onClose={page.closePanel} onOpenEditPlace={(place) => { page.closePanel(); page.openEdit(place); }}
      onSave={rule ? (next) => void page.changeRule(rule, next) : undefined}
      onRemove={rule ? () => page.setRemoving(row) : undefined}>
      {children}
    </CodingRulePanel>
  );
}

const CODING_RULE_COLUMNS: DataTableColumn<CodingRuleRow>[] = [
  { key: "what", header: "What", nowrap: true, render: (row) => row.what },
  { key: "rule", header: "Rule", grow: true, render: (row) => (
    <span className="coding-rules__text" title={row.pattern}>
      {row.rule.map((part, index) => (typeof part === "string"
        ? <span key={index}>{part}</span> : <code key={index} className="coding-rules__code">{part.code}</code>))}
    </span>
  ) },
  { key: "applies", header: "Applies to", nowrap: true,
    render: (row) => <span className="coding-rules__cell" data-label="Applies to">{row.appliesTo}</span> },
  { key: "source", header: "Source", nowrap: true,
    render: (row) => <span className="coding-rules__cell coding-rules__source" data-label="Source">{row.sources.join(" · ")}</span> },
];
