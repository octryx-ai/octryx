import { useState } from "react";

import { SettingsDrawer } from "../projectsTab/SettingsDrawer";
import { OptionCards } from "../settingsKit/SettingsKit";
import type { RuleDraft, RuleKind, ToolRule } from "./workspaceSettingsModel";
import { FILE_TOOLS, RULE_KINDS, ruleDraftProblems, ruleFromDraft } from "./workspaceSettingsModel";

// Add a command & file rule: a closed set of rule kinds, each with only the
// fields it needs. The server validates the rule again when the section is saved.
export function CodingRuleDrawer({ taken, onClose, onAdd }: {
  taken: string[];
  onClose: () => void;
  onAdd: (rule: ToolRule) => void;
}) {
  const [draft, setDraft] = useState<RuleDraft>({ kind: "command_prefix_denied", command: "", argument: "", glob: "" });
  const problems = ruleDraftProblems(draft);
  const update = (patch: Partial<RuleDraft>) => setDraft({ ...draft, ...patch });
  return (
    <SettingsDrawer eyebrow="Command & file rules" title="Add rule" size="detail" onClose={onClose}
      footer={(
        <>
          <button type="button" className="admin-panel__action-btn" onClick={onClose}>Cancel</button>
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="coding-rule-add"
            disabled={problems.length > 0} onClick={() => onAdd(ruleFromDraft(draft, taken))}>Add rule</button>
        </>
      )}>
      <div className="sk-page">
        <OptionCards<RuleKind> name="coding-rule-kind" label="Kind of rule" value={draft.kind} onChange={(kind) => update({ kind })}
          options={RULE_KINDS.map((item) => ({ value: item.kind, title: item.label, desc: item.desc }))} />
        {draft.kind === "path_denied" ? (
          <label className="admin-panel__field">
            <span>Path pattern (glob)</span>
            <input className="admin-users__toolbar-input" value={draft.glob} data-testid="coding-rule-glob"
              onChange={(event) => update({ glob: event.target.value })} />
            <span className="sk-sub">Applies to the file tools {FILE_TOOLS.join(", ")}.</span>
          </label>
        ) : (
          <>
            <label className="admin-panel__field">
              <span>{draft.kind === "command_prefix_denied" ? "Command (the words it starts with)" : "Command"}</span>
              <input className="admin-users__toolbar-input" value={draft.command} data-testid="coding-rule-command"
                onChange={(event) => update({ command: event.target.value })} />
            </label>
            {draft.kind !== "command_prefix_denied" ? (
              <label className="admin-panel__field">
                <span>Argument</span>
                <input className="admin-users__toolbar-input" value={draft.argument} data-testid="coding-rule-argument"
                  onChange={(event) => update({ argument: event.target.value })} />
              </label>
            ) : null}
          </>
        )}
        {problems.length ? <ul className="sk-note">{problems.map((line) => <li key={line}>{line}</li>)}</ul> : null}
      </div>
    </SettingsDrawer>
  );
}
