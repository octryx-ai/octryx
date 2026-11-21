// Instant feedback in the side panel: what the backend would refuse about one box (workflow_runs/graph.py
// _validate_node / _validate_phase / decider), said in plain words at the field it concerns. The backend stays the
// authority; the canvas core merges its messages with these.
import type { DefNode, DesignerCatalog, FieldIssue } from "../types";
import { resultValues } from "./exitValues";
import { CAPABILITY_ORDER, OPERATORS_BY_KIND, capabilityName, exitName, toolName } from "./labels";
import { ON_OPEN_HIGH_KEY, onOpenHighIssue } from "./onOpenHigh";

const text = (value: unknown) => (typeof value === "string" ? value.trim() : "");
const record = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
const list = (value: unknown) => (Array.isArray(value) ? value : []);

// Tools that write without the path decision (backend path_rules.PATH_UNCHECKED_TOOLS).
export const SHELL_TOOLS = ["bash", "run_cli_command", "run_validation_commands"];
const DECIDER_VALUES = ["requester", "item_owner", "handoff_owner", "spec_origin"];

function phaseIssues(node: DefNode, catalog: DesignerCatalog): FieldIssue[] {
  const issues: FieldIssue[] = [];
  const config = node.config ?? {};
  const contract = record(config.workflow_contract);
  const agentKey = text(config.agent);
  const agent = catalog.agents.find((item) => item.key === agentKey);
  if (!agentKey) issues.push({ path: "config.agent", message: "Choose the agent that does this step." });
  else if (!agent) issues.push({ path: "config.agent", message: "This agent no longer exists. Choose another one." });
  if (!contract) {
    issues.push({ path: "config.workflow_contract", message: "Say what this step may do and when it is done." });
    return issues;
  }
  for (const key of ["workflow_id", "workflow_class"] as const) {
    if (!text(contract[key]) && !text(config[key]))
      issues.push({ path: `config.workflow_contract.${key}`,
        message: "This step has no technical name yet. Change any setting of the step and it is set by itself." });
  }
  const capability = text(contract.capability_class);
  if (!CAPABILITY_ORDER.includes(capability as (typeof CAPABILITY_ORDER)[number]))
    issues.push({ path: "config.workflow_contract.capability_class", message: "Choose what this step may do." });
  else if (agent && CAPABILITY_ORDER.indexOf(capability as never) > CAPABILITY_ORDER.indexOf(agent.capability_ceiling))
    issues.push({ path: "config.workflow_contract.capability_class",
      message: `${agent.name} may do at most: ${capabilityName(agent.capability_ceiling)}.` });
  const steps = list(contract.source_steps).filter((step) => text(record(step)?.tool));
  const checks = list(contract.checks);
  if (!steps.length && !checks.length)
    issues.push({ path: "config.workflow_contract.checks",
      message: "Add at least one “done when” check or required step, so the run knows when this step is done." });
  list(contract.source_steps).forEach((step, index) => {
    if (!text(record(step)?.tool))
      issues.push({ path: `config.workflow_contract.source_steps.${index}.tool`, message: "Choose the tool of this step." });
  });
  checks.forEach((check, index) => {
    const type = text(record(check)?.type);
    if (!type) issues.push({ path: `config.workflow_contract.checks.${index}.type`, message: "Choose what is checked." });
    else if (!catalog.checkTypes.some((item) => item.type === type))
      issues.push({ path: `config.workflow_contract.checks.${index}.type`, message: "This kind of check is not known." });
  });
  const results = config.result_values;
  if (results !== undefined) {
    const values = list(results).map(text);
    if (!Array.isArray(results) || values.some((value) => !value))
      issues.push({ path: "config.result_values", message: "Each possible result needs a name." });
    else if (new Set(values).size !== values.length)
      issues.push({ path: "config.result_values", message: "Each possible result may appear only once." });
    else if (values.includes("otherwise"))
      issues.push({ path: "config.result_values", message: "“Otherwise” is taken by conditions; choose another name." });
  }
  const rules = contract.path_rules;
  if (rules !== undefined && rules !== null) {
    const body = record(rules);
    if (!body || !Object.keys(body).length || Object.keys(body).some((key) => !["write", "create", "protect_confirmed_tests"].includes(key)))
      issues.push({ path: "config.workflow_contract.path_rules", message: "Where it may write: use the fields below." });
    else {
      for (const key of ["write", "create"] as const) {
        const patterns = body[key];
        if (patterns !== undefined && (!Array.isArray(patterns) || !patterns.length || !patterns.every((item) => text(item))))
          issues.push({ path: `config.workflow_contract.path_rules.${key}`, message: "List at least one path, one per line." });
      }
      if (body.create !== undefined && body.protect_confirmed_tests !== true)
        issues.push({ path: "config.workflow_contract.path_rules.create",
          message: "New files can only be allowed when the confirmed tests are protected." });
      const allowed = list(record(config.tool_policy)?.allowlist).map(text);
      const shells = SHELL_TOOLS.filter((tool) => allowed.includes(tool));
      if (shells.length)
        issues.push({ path: "config.tool_policy.allowlist",
          message: `With write limits the step cannot use ${shells.map(toolName).join(", ")}: a shell could write anywhere.` });
    }
  }
  return issues;
}

function fieldConditionIssues(config: Record<string, unknown>, catalog: DesignerCatalog): FieldIssue[] {
  const issues: FieldIssue[] = [];
  const field = (catalog.workItemFields ?? []).find((item) => item.key === text(config.field));
  if (!field) {
    issues.push({ path: "config.field", message: text(config.field) ? "This field of the ticket is not known." : "Choose the field of the ticket." });
    return issues;
  }
  if (!(OPERATORS_BY_KIND[field.kind] ?? []).includes(text(config.operator)))
    issues.push({ path: "config.operator", message: "Choose how the field is compared." });
  const value = config.value;
  if (field.kind === "number") {
    if (typeof value !== "number" || !Number.isFinite(value)) issues.push({ path: "config.value", message: "Enter a number to compare with." });
  } else if (!text(value)) {
    issues.push({ path: "config.value", message: "Enter the value to compare with." });
  } else if (field.kind === "enum" && field.values?.length && !field.values.includes(text(value))) {
    issues.push({ path: "config.value", message: `${field.label} never has this value.` });
  }
  return issues;
}

export function nodeConfigIssues(node: DefNode, nodes: DefNode[], catalog: DesignerCatalog): FieldIssue[] {
  const config = node.config ?? {};
  const issues: FieldIssue[] = [];
  if (!text(node.label)) issues.push({ path: "label", message: "Give this box a name." });
  const decider = config.decider;
  if (decider !== undefined && (typeof decider !== "string"
      || !(DECIDER_VALUES.includes(decider) || (decider.startsWith("role:") && catalog.deciders.includes(decider)))))
    issues.push({ path: "config.decider", message: "Choose who decides." });
  const openHigh = onOpenHighIssue(node.type, config);
  if (openHigh) issues.push({ path: `config.${ON_OPEN_HIGH_KEY}`, message: openHigh });
  switch (node.type) {
    case "phase":
      return [...issues, ...phaseIssues(node, catalog)];
    case "gate": {
      const checks = list(config.checks);
      if (!checks.length) issues.push({ path: "config.checks", message: "Add at least one check." });
      checks.forEach((check, index) => {
        const type = text(record(check)?.type);
        if (!catalog.gateCheckTypes.includes(type))
          issues.push({ path: `config.checks.${index}.type`,
            message: type ? "A check box cannot judge this kind of check." : "Choose what is checked." });
      });
      const phase = text(config.phase);
      if (phase && !nodes.some((item) => item.id === phase && item.type === "phase"))
        issues.push({ path: "config.phase", message: "This agent step no longer exists." });
      return issues;
    }
    case "decision": {
      if (config.check === "field") return [...issues, ...fieldConditionIssues(config, catalog)];
      const source = nodes.find((item) => item.id === text(config.source));
      const allowed = source ? resultValues(source, catalog) : null;
      if (!source || !allowed?.length) {
        issues.push({ path: "config.source", message: "Choose the box whose result this condition looks at." });
        return issues;
      }
      const options = list(config.options).map(text).filter(Boolean);
      if (!options.length) issues.push({ path: "config.options", message: "Choose at least one result to branch on." });
      const unknown = options.filter((option) => !allowed.includes(option));
      if (unknown.length)
        issues.push({ path: "config.options",
          message: `${source.label || "That box"} never ends with: ${unknown.map(exitName).join(", ")}.` });
      return issues;
    }
    case "outcome":
      if (!catalog.outcomes.includes(text(config.outcome)))
        issues.push({ path: "config.outcome", message: "Choose how the workflow ends here." });
      return issues;
    case "platform_action": {
      const action = text(config.action);
      if (action) {
        if (!catalog.platformActions.some((item) => item.key === action))
          issues.push({ path: "config.action", message: "This platform action is not known." });
      } else if (!text(config.tool)) {
        issues.push({ path: "config.action", message: "Choose a platform action (or, under Technical details, a tool)." });
      }
      if ("arguments" in config && !record(config.arguments))
        issues.push({ path: "config.arguments", message: "The arguments must be a set of named values." });
      return issues;
    }
    case "user_confirmation":
      if (!catalog.confirmationSubjects.includes(text(config.subject)))
        issues.push({ path: "config.subject", message: "Choose what the person confirms." });
      return issues;
    case "user_conversation":
      if (!text(config.question)) issues.push({ path: "config.question", message: "Write the question the person is asked." });
      return issues;
    case "watch": {
      const conditions = list(config.conditions).map(text).filter(Boolean);
      if (!conditions.length) issues.push({ path: "config.conditions", message: "Choose at least one event to wait for." });
      else if (conditions.some((item) => !catalog.watchConditions.includes(item)))
        issues.push({ path: "config.conditions", message: "One of these events is not known." });
      return issues;
    }
    case "sub_workflow": {
      const key = text(config.workflow_key);
      if (!key) issues.push({ path: "config.workflow_key", message: "Choose the workflow that runs here." });
      else if (!catalog.workflows.some((item) => item.key === key))
        issues.push({ path: "config.workflow_key", message: "This workflow is not published (any more)." });
      return issues;
    }
    default:
      return issues;
  }
}
