// Inspector form for an agent step: agent, capability, checks, steps, results, tools, file rules and limits.
import { ChipInput, NumberField, Problems, SelectField, Technical, TextField, ToggleField } from "./fields";
import { ChecksEditor, StepsEditor } from "./InspectorListEditors";
import { ToolsEditor } from "./InspectorToolsEditor";
import { objects, record, strings, text, toolChoices, type FormProps } from "./inspectorValues";
import { CAPABILITY_ORDER, capabilityName, exitName, paramName } from "./labels";
import { SHELL_TOOLS } from "./nodeIssues";
import { issuesAt, setIn } from "./patch";

export function PhaseForm({ node, catalog, editable, issues, set, setAll }: FormProps) {
  const config = node.config ?? {};
  const contract = record(config.workflow_contract);
  const agent = catalog.agents.find((item) => item.key === text(config.agent));
  const ceiling = agent ? CAPABILITY_ORDER.indexOf(agent.capability_ceiling) : CAPABILITY_ORDER.length - 1;
  const rules = record(contract.path_rules);
  const hasRules = contract.path_rules !== undefined;
  const allowlist = strings(record(config.tool_policy).allowlist);
  const setRules = (key: string, value: unknown) => {
    const next = setIn(rules, key, value);
    set("workflow_contract.path_rules", Object.keys(next).length ? next : undefined);
  };
  return (
    <>
      <SelectField label="Agent" value={text(config.agent)} disabled={!editable} issues={issuesAt(issues, "config.agent")}
        options={catalog.agents.map((item) => ({ value: item.key, label: item.name }))}
        onChange={(key) => set("agent", key)} />
      <SelectField label="What it may do" value={text(contract.capability_class)} disabled={!editable}
        issues={issuesAt(issues, "config.workflow_contract.capability_class")}
        hint={agent ? `${agent.name} may do at most: ${capabilityName(agent.capability_ceiling)}.` : undefined}
        options={CAPABILITY_ORDER.filter((_item, index) => index <= ceiling)
          .map((item) => ({ value: item, label: capabilityName(item) }))}
        onChange={(value) => set("workflow_contract.capability_class", value)} />
      <ChecksEditor checks={objects(contract.checks)} types={catalog.checkTypes} tools={toolChoices(catalog)}
        base="config.workflow_contract.checks"
        title="Done when" empty="Nothing checked yet. Add a check (or a required step below), so the run knows when this step is done."
        editable={editable} issues={issuesAt(issues, "config.workflow_contract.checks")}
        set={(checks) => set("workflow_contract.checks", checks)} />
      <StepsEditor contract={contract} catalog={catalog} editable={editable}
        issues={issuesAt(issues, "config.workflow_contract.source_steps")}
        set={(steps) => set("workflow_contract.source_steps", steps)} />
      <section className="dsi-group" aria-label="Possible results">
        <h4 className="dsi-group__title">Possible results</h4>
        <ChipInput label="The agent ends with one of" values={strings(config.result_values)} disabled={!editable}
          placeholder="e.g. Fix needed" addLabel="Add result" format={exitName}
          hint="Optional. A condition after this step can branch on these results."
          issues={issuesAt(issues, "config.result_values")}
          onChange={(values) => set("result_values", values.length
            ? values.map((value) => value.trim().toLowerCase().replace(/\s+/g, "_")) : undefined)} />
      </section>
      <ToolsEditor allowlist={allowlist} catalog={catalog} editable={editable} hasRules={hasRules}
        issues={issuesAt(issues, "config.tool_policy.allowlist")} set={(values) => set("tool_policy.allowlist", values)} />
      <section className="dsi-group" aria-label="Writing files">
        <h4 className="dsi-group__title">Writing files</h4>
        <ToggleField label="Set rules for writing files" checked={hasRules} disabled={!editable}
          hint={hasRules ? undefined : "Off: the step may write wherever its tools allow."}
          onChange={(on) => {
            setAll([
              ["workflow_contract.path_rules", on ? { protect_confirmed_tests: true } : undefined],
              ...(on ? [["tool_policy.allowlist", allowlist.filter((tool) => !SHELL_TOOLS.includes(tool))] as [string, unknown]] : []),
            ]);
          }} />
        <Problems issues={issues.filter((issue) => issue.path === "config.workflow_contract.path_rules")} />
        {hasRules ? (
          <>
            <ChipInput label="May only change files in" values={strings(rules.write)} disabled={!editable}
              placeholder="e.g. src/**" addLabel="Add folder"
              hint="Optional. ** means any folder below. None: no folder limit."
              issues={issuesAt(issues, "config.workflow_contract.path_rules.write")}
              onChange={(values) => setRules("write", values.length ? values : undefined)} />
            <ToggleField label="Protect the confirmed tests" checked={rules.protect_confirmed_tests === true}
              disabled={!editable}
              hint="The tests a person confirmed stay as they are. The step changes only existing files and creates new ones only where allowed below."
              onChange={(on) => setRules("protect_confirmed_tests", on ? true : undefined)} />
            <ChipInput label="May create new files in" values={strings(rules.create)}
              disabled={!editable || rules.protect_confirmed_tests !== true} placeholder="e.g. tests/**" addLabel="Add folder"
              hint={rules.protect_confirmed_tests === true ? "Optional." : "Only when the confirmed tests are protected."}
              issues={issuesAt(issues, "config.workflow_contract.path_rules.create")}
              onChange={(values) => setRules("create", values.length ? values : undefined)} />
          </>
        ) : null}
      </section>
      <Technical open={issuesAt(issues, "config.workflow_contract.workflow_id").length > 0
        || issuesAt(issues, "config.workflow_contract.workflow_class").length > 0}>
        <TextField label="Technical name" value={text(contract.workflow_id) || text(config.workflow_id)} disabled={!editable}
          issues={issuesAt(issues, "config.workflow_contract.workflow_id")}
          onChange={(value) => set("workflow_contract.workflow_id", value)} />
        <TextField label="Technical kind" value={text(contract.workflow_class) || text(config.workflow_class)}
          disabled={!editable} issues={issuesAt(issues, "config.workflow_contract.workflow_class")}
          onChange={(value) => set("workflow_contract.workflow_class", value)} />
      </Technical>
      {Object.keys(record(contract.limits)).length ? (
        <section className="dsi-group" aria-label="Limits">
          <h4 className="dsi-group__title">Limits</h4>
          {Object.entries(record(contract.limits)).map(([key, value]) => (
            <NumberField key={key} label={paramName(key)} min={1} disabled={!editable}
              value={typeof value === "number" ? value : null}
              onChange={(next) => set(`workflow_contract.limits.${key}`, next ?? undefined)} />
          ))}
        </section>
      ) : null}
    </>
  );
}
