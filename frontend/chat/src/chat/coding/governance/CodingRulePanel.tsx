import { useState, type ReactNode } from "react";

import { ActionMenu } from "../../../admin/components/workflowSurfaces/ActionMenu";
import { OptionCards } from "../../../admin/components/settingsKit/SettingsKit";
import {
  FILE_TOOLS, RULE_KINDS, ruleDraftProblems, ruleFromDraft, type RuleDraft, type RuleKind, type ToolRule,
} from "../../../admin/components/workspaceSettings/workspaceSettingsModel";
import { FormSection } from "../../../layout/FormSection";
import { SidePanel } from "../../../layout/SidePanel";
import { ruleText, type CodingRuleRow, type RuleEditPlace } from "./codingRulesTable";

// Coding › Rules: a row opens its rule in the side panel. A Workspace command & file rule can be
// changed there and removed (⋯), saved the way "Add rule" saves it (the Workspace's coding settings); a built-in rule,
// a policy, an approval or a check is read only and names its source and the place it is changed. "Add rule" opens
// the same panel empty. A field's problem shows once the person tries to save, not before they type.

export const EDIT_PLACES: Record<RuleEditPlace, string> = {
  workspaceCoding: "Workspace settings › Coding tools & devices",
  cedarPolicies: "Settings › Policies",
  policies: "Tool & approval policies",
  approvalRule: "Approval rule",
  pipeline: "Delivery pipeline",
};

const SOURCE_WORDS: Record<string, string> = {
  "Built-in": "Built in: applies to every Workspace",
  Workspace: "This Workspace's command & file rules",
  "Not in a policy yet": "A protected-path rule that is not in a policy yet",
};

/** A built-in rule only: it applies to every Workspace and is not changed in a Workspace. */
export function builtInOnly(row: CodingRuleRow): boolean {
  return row.sources.includes("Built-in") && !row.sources.includes("Workspace");
}

/** The draft of a stored rule, for its edit form. */
export function draftOf(rule: ToolRule | null): RuleDraft {
  if (!rule) return { kind: "command_prefix_denied", command: "", argument: "", glob: "" };
  return {
    kind: rule.kind,
    command: (rule.kind === "command_prefix_denied" ? rule.prefix ?? [] : rule.command ?? []).join(" "),
    argument: rule.argument ?? "",
    glob: rule.glob ?? "",
  };
}

/** The rule as saved: a changed rule keeps its id, so its history and the server's references stay. */
export function savedRule(draft: RuleDraft, current: ToolRule | null, taken: string[]): ToolRule {
  const next = ruleFromDraft(draft, taken.filter((id) => id !== current?.id));
  if (!current) return next;
  // A path rule keeps the file tools it was set up with.
  const tools = current.kind === "path_denied" && next.kind === "path_denied" && current.tools?.length ? current.tools : next.tools;
  return { ...next, id: current.id, ...(tools ? { tools } : {}) };
}

export function CodingRulePanel({
  row, rule, taken, busy = false, error = null, onClose, onSave, onRemove, onOpenEditPlace, children,
}: {
  // The row the panel shows; null when adding a rule.
  row: CodingRuleRow | null;
  // The Workspace rule behind the row, when this person may change it.
  rule: ToolRule | null;
  taken: string[];
  busy?: boolean;
  error?: string | null;
  onClose: () => void;
  onSave?: (rule: ToolRule) => void;
  onRemove?: () => void;
  onOpenEditPlace: (place: RuleEditPlace) => void;
  // A confirmation asked from the panel (Remove), rendered inside it.
  children?: ReactNode;
}) {
  const editable = !row || Boolean(rule && onSave);
  const [draft, setDraft] = useState<RuleDraft>(() => draftOf(rule));
  const [attempted, setAttempted] = useState(false);
  const problems = ruleDraftProblems(draft);
  const update = (patch: Partial<RuleDraft>) => setDraft((current) => ({ ...current, ...patch }));
  const title = row ? row.what : "Add rule";
  const subtitle = row ? ruleText(row.rule) : undefined;

  const save = () => {
    setAttempted(true);
    if (problems.length || !onSave) return;
    onSave(savedRule(draft, rule, taken));
  };

  const readOnly = row && !editable ? (
    <dl className="coding-rule-panel__facts" data-testid="coding-rule-facts">
      <dt>Rule</dt><dd>{ruleText(row.rule)}</dd>
      {row.pattern ? <><dt>Pattern</dt><dd><code className="coding-rules__code">{row.pattern}</code></dd></> : null}
      <dt>Applies to</dt><dd>{row.appliesTo}</dd>
      <dt>Source</dt><dd>{row.sources.map((source) => SOURCE_WORDS[source] ?? source).join(" · ")}</dd>
      {builtInOnly(row) ? null : (
        <>
          <dt>Changed in</dt>
          <dd>
            <button type="button" className="work-link" data-testid="coding-rule-edit-place"
              onClick={() => onOpenEditPlace(row.edit)}>{EDIT_PLACES[row.edit]}</button>
          </dd>
        </>
      )}
    </dl>
  ) : null;

  const form = editable ? (
    <>
      <FormSection title="Kind of rule">
        <OptionCards<RuleKind> name="coding-rule-kind" label="Kind of rule" value={draft.kind} onChange={(kind) => update({ kind })}
          options={RULE_KINDS.map((item) => ({ value: item.kind, title: item.label, desc: item.desc }))} />
      </FormSection>
      <FormSection title="Rule">
        {draft.kind === "path_denied" ? (
          <>
            <label className="admin-panel__field">
              <span>Path pattern (glob)</span>
              <input className="admin-panel__input" value={draft.glob} data-testid="coding-rule-glob" placeholder="**/.env"
                onChange={(event) => update({ glob: event.target.value })} />
            </label>
            <p className="coding-rule-panel__hint">Applies to the file tools {(rule?.kind === "path_denied" && rule.tools?.length
              ? rule.tools : FILE_TOOLS).join(", ")}.</p>
          </>
        ) : (
          <>
            <label className="admin-panel__field">
              <span>{draft.kind === "command_prefix_denied" ? "Command (the words it starts with)" : "Command"}</span>
              <input className="admin-panel__input" value={draft.command} data-testid="coding-rule-command"
                onChange={(event) => update({ command: event.target.value })} />
            </label>
            {draft.kind !== "command_prefix_denied" ? (
              <label className="admin-panel__field">
                <span>Argument</span>
                <input className="admin-panel__input" value={draft.argument} data-testid="coding-rule-argument"
                  onChange={(event) => update({ argument: event.target.value })} />
              </label>
            ) : null}
          </>
        )}
        {attempted && problems.length ? (
          <ul className="coding-rule-panel__problems" role="alert" data-testid="coding-rule-problems">
            {problems.map((line) => <li key={line}>{line}</li>)}
          </ul>
        ) : null}
      </FormSection>
      {row ? (
        <p className="coding-rule-panel__source">Source: {row.sources.map((source) => SOURCE_WORDS[source] ?? source).join(" · ")}</p>
      ) : null}
    </>
  ) : null;

  return (
    <SidePanel title={title} subtitle={subtitle} onClose={onClose} testId="coding-rule-panel"
      headerActions={row && editable && onRemove ? (
        <ActionMenu row={{ objectName: subtitle || title }} items={[
          { label: "Remove rule", danger: true, onSelect: onRemove, testId: "coding-rule-remove" },
        ]} />
      ) : undefined}
      footer={editable ? (
        <>
          <button type="button" className="admin-panel__action-btn" onClick={onClose}>Cancel</button>
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" disabled={busy}
            data-testid={row ? "coding-rule-save" : "coding-rule-add"} onClick={save}>{row ? "Save rule" : "Add rule"}</button>
        </>
      ) : undefined}>
      {error ? <div className="work-area__error" role="alert">{error}</div> : null}
      {readOnly}
      {form}
      {children}
    </SidePanel>
  );
}
