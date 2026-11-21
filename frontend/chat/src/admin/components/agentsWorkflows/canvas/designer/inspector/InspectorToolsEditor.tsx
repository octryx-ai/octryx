// Tools editor of the node inspector: the allowed tools as one summary line opening to grouped chips.
import { useState } from "react";

import type { DesignerCatalog, FieldIssue } from "../types";
import { Card, PickList, Problems } from "./fields";
import { toolChoices } from "./inspectorValues";
import { TOOL_GROUP_NAMES, toolGroup, toolName, type ToolGroup } from "./labels";
import { SHELL_TOOLS } from "./nodeIssues";

/** "runs tests" when the only command tools are test runners, "may run commands" otherwise. */
function runSummary(allowlist: string[]): string | null {
  const run = allowlist.filter((tool) => toolGroup(tool) === "run");
  if (!run.length) return null;
  return run.every((tool) => /test/.test(tool)) ? "runs tests" : "may run commands";
}

/** The allowed tools as one summary line ("16 tools · may change files"), opening to chips grouped by kind. */
export function ToolsEditor({ allowlist, catalog, editable, issues, hasRules, set }: {
  allowlist: string[]; catalog: DesignerCatalog; editable: boolean; issues: FieldIssue[]; hasRules: boolean;
  set: (values: string[]) => void;
}) {
  const [open, setOpen] = useState(issues.length > 0);
  const groups = (Object.keys(TOOL_GROUP_NAMES) as ToolGroup[])
    .map((group) => ({ group, tools: allowlist.filter((tool) => toolGroup(tool) === group) }))
    .filter((item) => item.tools.length);
  const summary = allowlist.length
    ? [`${allowlist.length} ${allowlist.length === 1 ? "tool" : "tools"}`,
      groups.some((item) => item.group === "change") ? "may change files" : "reads only",
      runSummary(allowlist)].filter(Boolean).join(" · ")
    : "The agent's own tools";
  const choices = toolChoices(catalog)
    .filter((tool) => !hasRules || !SHELL_TOOLS.includes(tool.value) || allowlist.includes(tool.value));
  return (
    <section className="dsi-group" aria-label="Tools it may use">
      <h4 className="dsi-group__title">Tools it may use</h4>
      <Card title={summary} open={open} onToggle={() => setOpen(!open)} problem={issues.length > 0}
        meta={open ? undefined : groups.map((item) => `${TOOL_GROUP_NAMES[item.group]} ${item.tools.length}`).join(", ")}>
        {groups.map(({ group, tools }) => (
          <PickList key={group} label={TOOL_GROUP_NAMES[group]} disabled={!editable} values={tools}
            options={tools.map((tool) => ({ value: tool, label: toolName(tool) }))} addLabel="" emptyText="" issues={issues.filter((issue) => tools.some((tool) => issue.message.includes(toolName(tool))))}
            onChange={(values) => set([...allowlist.filter((tool) => toolGroup(tool) !== group), ...values])} />
        ))}
        {!allowlist.length ? <p className="admin-panel__hint">None chosen: the agent's own tools apply.</p> : null}
        {editable ? (
          <PickList label="Add more" values={[]} options={choices.filter((tool) => !allowlist.includes(tool.value))}
            addLabel="Add a tool…" emptyText="" onChange={(values) => set([...allowlist, ...values])} />
        ) : null}
        {hasRules ? <span className="admin-panel__hint">With rules for writing files, shell tools stay off.</span> : null}
        <Problems issues={issues.filter((issue) => !allowlist.some((tool) => issue.message.includes(toolName(tool))))} />
      </Card>
    </section>
  );
}
