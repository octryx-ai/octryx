// A box of the phased workflow designer explained in plain words: who or what runs it, what
// it may do ("Writes only test files" instead of a glob list), what it checks and where each result leads. The
// raw settings stay available under "Details". Pure.
import { checkTypeLabel } from "./checkTypeLabels";
import { actionWords, edgeLabel, edgeTone, familyLabel, nodeFamily, whenWords } from "./phasedGraphWords";
import { type EdgeTone } from "./phasedGraphTypes";
import { onOpenHighSentence } from "./designer/inspector/onOpenHigh";
import type { PhasedEdge, PhasedNode } from "./phasedWorkflowModel";

type Json = Record<string, unknown>;

const record = (value: unknown): Json => (value && typeof value === "object" && !Array.isArray(value) ? (value as Json) : {});
const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const text = (value: unknown): string => (typeof value === "string" ? value : "");
const words = (value: string) => value.replace(/[._]+/g, " ").trim();

// --- path rules in words ----------------------------------------------------------------------------------------

const TEST_PATH = /(^|\/)(tests?|__tests__|spec|specs)(\/|$)|(^|\/)test_|_test\.|Test\.|\.test\.|_spec\.|\.spec\./;
const DOC_PATH = /(^|\/)(docs?|documentation)(\/|$)|\.(md|mdx|adoc|rst|txt)$|(^|\/)README/i;

export function summarizeWritePaths(patterns: string[]): string {
  const globs = patterns.map((item) => item.trim()).filter(Boolean);
  if (!globs.length) return "";
  const tests = globs.every((glob) => TEST_PATH.test(glob));
  if (tests) return "Writes only test files";
  const docs = globs.every((glob) => DOC_PATH.test(glob));
  if (docs) return "Writes only documentation";
  if (globs.every((glob) => TEST_PATH.test(glob) || DOC_PATH.test(glob))) return "Writes only test files and documentation";
  const shown = globs.slice(0, 3).join(", ");
  return globs.length > 3 ? `Writes only in ${shown} and ${globs.length - 3} more places` : `Writes only in ${shown}`;
}

// --- Tools in words -----------------------------------------------------------------------------------------------

const TOOL_GROUPS: Array<[string, RegExp]> = [
  ["read the code", /^(analyze_workspace_repository|code_search|grep_workspace|glob_workspace_files|list_workspace_directory|read_workspace_file|get_git_diff)$/],
  ["edit files", /^(write_workspace_file|edit_workspace_file|multi_edit_workspace_file|delete_workspace_file|move_workspace_file)$/],
  ["run the tests", /^run_test_suite$/],
  ["search the knowledge base", /^knowledge_(search|read)$/],
  ["read the ticket", /^(get_jira_ticket|work_item_context|jira_.*)$/],
  ["use helper agents", /^(spawn_sub_agent|get_context_from_subthreads)$/],
  ["keep a to-do list", /^todo_(read|write)$/],
];

export function summarizeTools(allowlist: string[]): string {
  const tools = [...new Set(allowlist.filter(Boolean))];
  if (!tools.length) return "";
  const said: string[] = [];
  let other = 0;
  for (const tool of tools) {
    const submit = /^submit_(.+)$/.exec(tool);
    const group = TOOL_GROUPS.find(([, pattern]) => pattern.test(tool))?.[0] ?? (submit ? `submit the ${words(submit[1])}` : "");
    if (!group) other += 1;
    else if (!said.includes(group)) said.push(group);
  }
  if (other) said.push(`${other} other ${other === 1 ? "tool" : "tools"}`);
  const sentence = said.length > 1 ? `${said.slice(0, -1).join(", ")} and ${said[said.length - 1]}` : said[0];
  return `Can ${sentence} (${tools.length} ${tools.length === 1 ? "tool" : "tools"})`;
}

// --- The panel ------------------------------------------------------------------------------------------------------

export type NodeExit = { label: string; target: string; tone: EdgeTone; loop: boolean };
export type NodeCheck = { label: string; blocking: boolean };

export type NodeDetails = {
  kindLabel: string;
  // Who or what runs this box.
  who: string;
  // What it does, in a sentence or two.
  what: string;
  // What it may and may not do (phases): class, writes, tools, protected tests.
  rules: string[];
  checks: NodeCheck[];
  exits: NodeExit[];
  // Arrows coming back here ("Fix ↔ test: from Green when failed, at most 3 times").
  loopsIn: string[];
  // Raw settings for "Details".
  raw: Json;
};

// The capability classes as awBadges names them (that module is .tsx; this one stays loadable by the unit tests).
const CLASS_WORDS: Record<string, string> = {
  read_only: "Read-only: may read, never change anything",
  change: "Change: may change files in the working folder",
  deliver: "Deliver: may change, push and publish",
};

const SUBJECT_WORDS: Record<string, string> = {
  reproduction: "The requester confirms that the failing test shows the reported bug.",
  test_contract: "The requester confirms the tests the change must make pass.",
  ticket_draft: "The requester confirms the ticket text.",
  retry_choice: "The requester decides: try again, clarify again or stop.",
  advance: "The requester decides whether the run goes on.",
  questions: "The requester answers the open questions.",
  documentation: "The requester confirms the documentation.",
  functional_acceptance: "The requester accepts the change functionally (or says it cannot be tested yet).",
  publication: "The requester confirms the publication.",
  followup: "The requester authorises the follow-up.",
  exception: "The requester takes a declared exception.",
};

function firstSentence(value: string): string {
  const match = /^(.+?[.!?])(\s|$)/.exec(value.trim());
  return match ? match[1] : value.trim();
}

function checksOf(raw: unknown): NodeCheck[] {
  return list(raw).map((item) => {
    const check = record(item);
    const type = text(check.type);
    return { label: text(check.description) || checkTypeLabel(type), blocking: check.blocking !== false };
  });
}

function whoAndWhat(node: PhasedNode, config: Json, workflowKey?: string): [string, string] {
  const contract = record(config.workflow_contract);
  switch (node.kind) {
    case "start":
      return ["The platform", "The run starts here when someone starts this workflow."];
    case "phase": {
      const agent = text(config.agent) || node.agent || "";
      const task = text(contract.when_to_use);
      return [agent ? `The ${agent} agent` : "An agent (none set)", task ? firstSentence(task) : "Works until its blocking checks pass."];
    }
    case "review":
      return ["An independent reviewer agent", "Reviews the change of the phase before it and records its verdict."];
    case "platform_action":
      return ["The platform (no agent)", `${actionWords(text(config.action) || node.action)}.`];
    case "gate":
      return ["The platform (no agent)", "Checks the evidence the last phase recorded; passes only if every blocking check passes."];
    case "decision":
      return ["The platform (no agent)", "Routes on the recorded result of an earlier step."];
    case "user_confirmation": {
      const subject = text(config.subject) || node.subject || "";
      const what = SUBJECT_WORDS[subject] ?? `The requester confirms the ${words(subject) || "result"}.`;
      return ["The requester", [what, onOpenHighSentence(config, workflowKey)].filter(Boolean).join(" ")];
    }
    case "user_conversation":
      return ["The requester", text(config.question) || node.question || "Answers a question."];
    case "approval":
      return ["A second person", "Approves or rejects before the run goes on (four-eyes)."];
    case "watch": {
      const conditions = list(config.conditions).map((item) => whenWords(text(item))).filter(Boolean);
      const auto = text(config.advance) === "confirm" ? " The requester confirms before the run goes on." : "";
      return ["The platform waits", `Waits until ${conditions.join(" or ") || "an external event"}.${auto}`];
    }
    case "pause":
      return ["The requester", "A platform step failed: the run waits for the requester to retry, change the plan or abort."];
    case "sub_workflow":
      return ["Another workflow", `Runs the workflow "${text(config.workflow_key) || node.workflow_key || "?"}" and continues on its result.`];
    case "outcome":
      return ["The platform", `The run ends as "${words(text(config.outcome) || node.outcome || "done")}".`];
    default:
      return ["The platform", ""];
  }
}

function rulesOf(node: PhasedNode, config: Json): string[] {
  if (node.kind !== "phase") return [];
  const contract = record(config.workflow_contract);
  const rules: string[] = [];
  const capability = text(contract.capability_class) || text(node.capability_class);
  if (capability) rules.push(CLASS_WORDS[capability] ?? `Class: ${words(capability)}`);
  const pathRules = record(contract.path_rules);
  const writes = list(pathRules.write).map(text);
  const fallback = node.path_rules ?? [];
  const summary = summarizeWritePaths(writes.length ? writes : fallback);
  if (summary) rules.push(summary);
  if (pathRules.protect_confirmed_tests === true) rules.push("Must keep the confirmed tests as they are");
  const tools = summarizeTools(list(record(config.tool_policy).allowlist).map(text));
  if (tools) rules.push(tools);
  return rules;
}

export function describeNode(node: PhasedNode, edges: PhasedEdge[], nodes: PhasedNode[], workflowKey?: string): NodeDetails {
  const config = record(node.config);
  const byId = new Map(nodes.map((item) => [item.id, item]));
  const title = (id: string) => byId.get(id)?.title || id;
  const [who, what] = whoAndWhat(node, config, workflowKey);
  const contract = record(config.workflow_contract);
  const checks = node.kind === "phase" ? checksOf(contract.checks) : node.kind === "gate" ? checksOf(config.checks) : [];
  const exits = edges
    .filter((edge) => edge.source === node.id)
    .map((edge) => ({
      label: edgeLabel(edge) || "then",
      target: title(edge.target),
      tone: edgeTone(edge, byId.get(edge.target)),
      loop: edge.kind === "loop",
    }));
  const loopsIn = edges
    .filter((edge) => edge.kind === "loop" && edge.target === node.id)
    .map((edge) => {
      const name = edge.title ? `${edge.title}: ` : "";
      const when = whenWords(edge.when);
      const limit = edge.max_iterations ? `, at most ${edge.max_iterations} ${edge.max_iterations === 1 ? "time" : "times"}` : "";
      return `${name}back from ${title(edge.source)}${when ? ` when ${when}` : ""}${limit}`;
    });
  const kindLabel = node.kind === "review" ? "Independent review" : familyLabel(nodeFamily(node.kind));
  return { kindLabel, who, what, rules: rulesOf(node, config), checks, exits, loopsIn, raw: config };
}
