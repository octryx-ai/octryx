// List editors of the node inspector: required steps and checks, each entry as an expandable card.
import { useState } from "react";

import type { DesignerCatalog, FieldIssue } from "../types";
import { Card, JsonObjectField, PickList, Problems, SelectField, Technical, TextField, ToggleField } from "./fields";
import { objects, record, strings, text, toolChoices, type Config } from "./inspectorValues";
import { paramName, stepModeName, toolName } from "./labels";
import { issuesAt } from "./patch";

/** Which entries of a list are open: the ones with a problem at first, then whatever the person opens or adds. */
function useOpen(initial: number[]) {
  const [open, setOpen] = useState<Set<number>>(() => new Set(initial));
  return {
    isOpen: (index: number) => open.has(index),
    toggle: (index: number) => setOpen((current) => {
      const next = new Set(current);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    }),
    opened: (index: number) => setOpen((current) => new Set(current).add(index)),
    removed: (index: number) => setOpen((current) => new Set([...current].filter((at) => at !== index)
      .map((at) => (at > index ? at - 1 : at)))),
  };
}

export function StepsEditor({ contract, catalog, editable, issues, set }: {
  contract: Config; catalog: DesignerCatalog; editable: boolean; issues: FieldIssue[]; set: (steps: Config[]) => void;
}) {
  const steps = objects(contract.source_steps);
  const base = "config.workflow_contract.source_steps";
  const cards = useOpen(steps.map((_step, index) => index).filter((index) => issuesAt(issues, `${base}.${index}`).length));
  const toolOptions = toolChoices(catalog);
  const update = (index: number, patch: Config) =>
    set(steps.map((step, at) => (at === index ? { ...step, ...patch } : step)));
  return (
    <section className="dsi-group" aria-label="Steps">
      <h4 className="dsi-group__title">Required steps (optional)</h4>
      {!steps.length ? (
        <p className="admin-panel__hint">
          Tools the agent must have used before this step counts as done, for example running the tests. Usually not needed.
        </p>
      ) : null}
      {steps.map((step, index) => {
        const path = `${base}.${index}`;
        const problems = issuesAt(issues, path);
        return (
          <Card key={index} open={cards.isOpen(index)} onToggle={() => cards.toggle(index)} problem={problems.length > 0}
            title={text(step.evidence_label) || (text(step.tool) ? toolName(text(step.tool)) : `Step ${index + 1}`)}
            meta={text(step.mode) ? stepModeName(text(step.mode)).split(" — ")[0] : undefined}
            removeLabel="Remove step"
            onRemove={editable ? () => { set(steps.filter((_item, at) => at !== index)); cards.removed(index); } : undefined}>
            <SelectField label="Tool" value={text(step.tool)} options={toolOptions}
              disabled={!editable} issues={issuesAt(issues, `${path}.tool`)} onChange={(tool) => update(index, { tool })} />
            <TextField label="What it shows (optional)" value={text(step.evidence_label)} disabled={!editable}
              placeholder="e.g. The failing test" onChange={(label) => update(index, { evidence_label: label || undefined })} />
            <SelectField label="How strict" value={text(step.mode)} disabled={!editable}
              empty="As the step's permissions suggest"
              options={["strict", "guided"].map((mode) => ({ value: mode, label: stepModeName(mode) }))}
              onChange={(mode) => update(index, { mode: mode || undefined })} />
          </Card>
        );
      })}
      {editable ? (
        <button type="button" className="admin-panel__action-btn dsi-add"
          onClick={() => { set([...steps, { tool: "" }]); cards.opened(steps.length); }}>
          Add a step
        </button>
      ) : null}
    </section>
  );
}

export function ChecksEditor({ checks, types, tools, base, title, empty, editable, issues, set }: {
  checks: Config[]; types: { type: string; label: string; params: string[] }[]; tools: { value: string; label: string }[];
  base: string; title: string; empty: string; editable: boolean; issues: FieldIssue[]; set: (checks: Config[]) => void;
}) {
  const cards = useOpen(checks.map((_check, index) => index).filter((index) => issuesAt(issues, `${base}.${index}`).length));
  const update = (index: number, patch: Config) =>
    set(checks.map((check, at) => (at === index ? { ...check, ...patch } : check)));
  return (
    <section className="dsi-group" aria-label={title}>
      <h4 className="dsi-group__title">{title}</h4>
      {issues.some((issue) => issue.path === base)
        ? <Problems issues={issues.filter((issue) => issue.path === base)} />
        : !checks.length ? <p className="admin-panel__hint">{empty}</p> : null}
      {checks.map((check, index) => {
        const path = `${base}.${index}`;
        const type = types.find((item) => item.type === text(check.type));
        const params = record(check.params);
        const problems = issuesAt(issues, path);
        return (
          <Card key={index} open={cards.isOpen(index)} onToggle={() => cards.toggle(index)} problem={problems.length > 0}
            title={text(check.description) || type?.label || `Check ${index + 1}`}
            meta={check.blocking === false ? "Only noted" : "Blocks"} removeLabel="Remove check"
            onRemove={editable ? () => { set(checks.filter((_item, at) => at !== index)); cards.removed(index); } : undefined}>
            <SelectField label="What is checked" value={text(check.type)} disabled={!editable}
              options={types.map((item) => ({ value: item.type, label: item.label }))}
              issues={issuesAt(issues, `${path}.type`)} onChange={(value) => update(index, { type: value, params: {} })} />
            <TextField label="In your words (optional)" value={text(check.description)} disabled={!editable}
              placeholder="e.g. The new test fails before the fix"
              onChange={(description) => update(index, { description: description || undefined })} />
            <ToggleField label="Blocks until it is met" checked={check.blocking !== false} disabled={!editable}
              hint="Off: it is only noted, the run goes on." onChange={(blocking) => update(index, { blocking })} />
            {(type?.params ?? []).map((param) => param === "tools" ? (
              <PickList key={param} label={paramName(param)} disabled={!editable} values={strings(params.tools)}
                options={tools} addLabel="Add a tool…" emptyText="No tool chosen yet."
                onChange={(values) => update(index, { params: { ...params, tools: values } })} />
            ) : (
              <TextField key={param} label={paramName(param)} disabled={!editable}
                value={Array.isArray(params[param]) ? strings(params[param]).join(", ") : text(params[param])}
                hint={param.endsWith("s") ? "Several values: separate them with commas." : undefined}
                onChange={(value) => update(index, {
                  params: { ...params, [param]: param.endsWith("s") ? value.split(",").map((v) => v.trim()).filter(Boolean) : value },
                })} />
            ))}
            <Technical>
              <JsonObjectField label="All parameters" value={params} disabled={!editable}
                onChange={(next) => update(index, { params: next })} />
            </Technical>
          </Card>
        );
      })}
      {editable ? (
        <button type="button" className="admin-panel__action-btn dsi-add"
          onClick={() => { set([...checks, { type: types[0]?.type ?? "", blocking: true }]); cards.opened(checks.length); }}>
          Add a check
        </button>
      ) : null}
    </section>
  );
}
