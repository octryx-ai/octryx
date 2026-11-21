// The side panel of a "Parallel work" box (teamwork WP-D, mock board 12): which agent step writes the work plan, the
// roles the plan may use (each runs as its own agent step: agent, model, what it may do) and whether independent
// items run at the same time. How many items and which roles a run really uses is the coordinator's plan.
import { useState } from "react";

import type { DefNode, DesignerCatalog, FieldIssue } from "../types";
import { Card, Problems, SelectField, TextField, ToggleField } from "./fields";
import { CAPABILITY_ORDER, capabilityName } from "./labels";
import { roleTemplate } from "./nodeDefaults";
import { issuesAt } from "./patch";
import { modelDisplayName } from "../../../../../../chat/header/runDetailsFacts";

type Config = Record<string, unknown>;

const text = (value: unknown) => (typeof value === "string" ? value : "");
const record = (value: unknown): Config =>
  value && typeof value === "object" && !Array.isArray(value) ? (value as Config) : {};

export const ROLE_NAME = /^[a-z][a-z0-9_-]{0,39}$/;

/** A free role name: "role", "role-2", … */
export function nextRoleName(roles: Config): string {
  if (!("role" in roles)) return "role";
  let n = 2;
  while (`role-${n}` in roles) n += 1;
  return `role-${n}`;
}

/** The roles with ``from`` renamed to ``to``, in the same order; unchanged when ``to`` is taken or not a role name. */
export function renameRole(roles: Config, from: string, to: string): Config {
  if (from === to || to in roles || !ROLE_NAME.test(to)) return roles;
  return Object.fromEntries(Object.entries(roles).map(([key, value]) => [key === from ? to : key, value]));
}

type Props = {
  node: DefNode;
  nodes: DefNode[];
  catalog: DesignerCatalog;
  editable: boolean;
  issues: FieldIssue[];
  set: (path: string, value: unknown) => void;
};

export function ParallelWorkForm({ node, nodes, catalog, editable, issues, set }: Props) {
  const config = node.config ?? {};
  const roles = record(config.roles);
  const names = Object.keys(roles);
  const [open, setOpen] = useState<Set<string>>(() => new Set());
  const [draftName, setDraftName] = useState<Record<string, string>>({});
  const toggle = (role: string) => setOpen((current) => {
    const next = new Set(current);
    if (next.has(role)) next.delete(role);
    else next.add(role);
    return next;
  });
  const setRole = (role: string, path: string, value: unknown) => set(`roles.${role}.${path}`, value);
  const planners = nodes.filter((item) => item.type === "phase" && item.id !== node.id);
  const roleIssues = issuesAt(issues, "config.roles");
  return (
    <>
      <SelectField label="Plan comes from" value={text(config.plan)} disabled={!editable} empty="Choose…"
        issues={issuesAt(issues, "config.plan")}
        hint="The agent step before this box that writes the work plan. “replan” leads back to it."
        options={planners.map((item) => ({ value: item.id, label: item.label || item.id }))}
        onChange={(plan) => set("plan", plan || undefined)} />
      <section className="dsi-group" aria-label="Roles the plan may use">
        <h4 className="dsi-group__title">Roles the plan may use</h4>
        <span className="admin-panel__hint">Each item of the plan runs as one of these roles, in its own session.</span>
        {!names.length ? <span className="admin-panel__hint">No role yet. Add at least one.</span> : null}
        {names.map((role) => {
          const template = record(roles[role]);
          const contract = record(template.workflow_contract);
          const agent = catalog.agents.find((item) => item.key === text(template.agent));
          const ceiling = agent ? CAPABILITY_ORDER.indexOf(agent.capability_ceiling) : CAPABILITY_ORDER.length - 1;
          const model = text(template.model);
          const meta = [agent?.name, model ? modelDisplayName(model) : "", capabilityName(text(contract.capability_class))]
            .filter(Boolean).join(" · ");
          const own = roleIssues.filter((issue) => issue.message.includes(`'${role}'`) || issue.path.startsWith(`config.roles.${role}`));
          const shownName = draftName[role] ?? role;
          return (
            <Card key={role} title={role} meta={meta} open={open.has(role)} problem={own.length > 0}
              onToggle={() => toggle(role)} removeLabel="Remove role"
              onRemove={editable ? () => set("roles", Object.fromEntries(Object.entries(roles).filter(([key]) => key !== role)))
                : undefined}>
              <TextField label="Role name" value={shownName} disabled={!editable}
                hint={ROLE_NAME.test(shownName) ? "Lower-case, e.g. backend." : "Lower-case letters, digits, - or _; starts with a letter."}
                onChange={(value) => {
                  const next = value.trim().toLowerCase();
                  setDraftName((current) => ({ ...current, [role]: value }));
                  const renamed = renameRole(roles, role, next);
                  if (renamed !== roles) {
                    set("roles", renamed);
                    setDraftName(({ [role]: _gone, ...rest }) => rest);
                    setOpen((current) => new Set([...current].map((key) => (key === role ? next : key))));
                  }
                }} />
              <SelectField label="Agent" value={text(template.agent)} disabled={!editable}
                options={catalog.agents.map((item) => ({ value: item.key, label: item.name }))}
                onChange={(key) => setRole(role, "agent", key)} />
              <TextField label="Model (optional)" value={model} disabled={!editable} placeholder="e.g. claude-haiku-5-5"
                hint={model ? `Shown as ${modelDisplayName(model)}.` : "Empty: the agent's own model."}
                onChange={(value) => setRole(role, "model", value.trim() || undefined)} />
              <SelectField label="What it may do" value={text(contract.capability_class)} disabled={!editable}
                hint={agent ? `${agent.name} may do at most: ${capabilityName(agent.capability_ceiling)}.` : undefined}
                options={CAPABILITY_ORDER.filter((_item, index) => index <= ceiling)
                  .map((item) => ({ value: item, label: capabilityName(item) }))}
                onChange={(value) => setRole(role, "workflow_contract.capability_class", value)} />
              <ToggleField label="Its items prove their change with a test" checked={template.needs_proof !== false}
                disabled={!editable} onChange={(on) => setRole(role, "needs_proof", on ? undefined : false)} />
              <Problems issues={own} />
            </Card>
          );
        })}
        {editable ? (
          <button type="button" className="admin-panel__action-btn" data-testid="parallel-add-role"
            onClick={() => {
              const name = nextRoleName(roles);
              set(`roles.${name}`, roleTemplate());
              setOpen((current) => new Set(current).add(name));
            }}>
            + Add role
          </button>
        ) : null}
        <Problems issues={roleIssues.filter((issue) => !names.some((role) => issue.message.includes(`'${role}'`)
          || issue.path.startsWith(`config.roles.${role}`)))} />
      </section>
      <ToggleField label="Items without dependencies run at the same time" checked={config.parallel !== false}
        disabled={!editable} hint={config.parallel === false ? "Off: one item after the other, each in its own session." : undefined}
        onChange={(on) => set("parallel", on ? undefined : false)} />
    </>
  );
}
