// Workflow designer D2b, the side panel's pure half: what a new box starts with, what the panel says is missing (the
// backend's rules in plain words), the results an arrow can stand for, and the patches the forms send. The shipped
// seed workflows are valid, so the panel must not find a problem in them.
import assert from "node:assert/strict";
import fs from "node:fs";
import { test } from "node:test";

import { OTHERWISE, exitValues, resultValues, routableSources } from "../../src/admin/components/agentsWorkflows/canvas/designer/inspector/exitValues.ts";
import { deciderName, exitName, kindName, paramName, toolName } from "../../src/admin/components/agentsWorkflows/canvas/designer/inspector/labels.ts";
import { DESIGNER_STEP_ID, defaultConfig } from "../../src/admin/components/agentsWorkflows/canvas/designer/inspector/nodeDefaults.ts";
import { nodeConfigIssues } from "../../src/admin/components/agentsWorkflows/canvas/designer/inspector/nodeIssues.ts";
import { edgeIssues, setIn } from "../../src/admin/components/agentsWorkflows/canvas/designer/inspector/patch.ts";
import { onOpenHighChoices, onOpenHighSentence } from "../../src/admin/components/agentsWorkflows/canvas/designer/inspector/onOpenHigh.ts";

const SEEDS = JSON.parse(fs.readFileSync(
  new URL("../../../../backend/app/services/workflow_runs/seeds/phased_workflows.json", import.meta.url), "utf8",
)).filter((seed) => seed.definition);

const GATE_CHECK_TYPES = ["tool_called", "tool_not_called", "evidence_count", "artifact_created", "citations_present",
  "test_command_passed", "tests_red", "tests_green", "confirmed_tests_intact", "ci_green", "reproduces", "review_passed",
  "slices_merged", "definition_of_ready", "lint_passed", "artefact_review_passed", "specification_ready", "evidence_families"];

const toNode = (raw) => ({ id: raw.id, type: raw.type, label: raw.label ?? "", config: raw.config ?? {} });
const toEdge = (raw) => ({ id: raw.id, source: raw.source_node_id, target: raw.target_node_id, kind: raw.kind ?? "next",
  when: raw.when ?? null, max_iterations: raw.max_iterations ?? null, label: raw.label });

// A catalog holding what the seeds use (the real one comes from GET /api/v1/phased-workflows/catalog).
// graph.py CONFIRMATION_SUBJECTS: literal keys plus SUBJECT_* constants.
const GRAPH = fs.readFileSync(new URL("../../../../backend/app/services/workflow_runs/graph.py", import.meta.url), "utf8");
const CONSTANTS = Object.fromEntries([...GRAPH.matchAll(/^(SUBJECT_[A-Z_]+) = "([a-z_]+)"$/gm)].map((match) => [match[1], match[2]]));
const BACKEND_SUBJECTS = /^CONFIRMATION_SUBJECTS = frozenset\(\{([^}]*)\}\)/m.exec(GRAPH)[1].split(",").map((item) => item.trim())
  .filter(Boolean).map((item) => (item.startsWith('"') ? item.slice(1, -1) : CONSTANTS[item]));

function catalogFor(definitions) {
  const nodes = definitions.flatMap((definition) => definition.nodes.map(toNode));
  const edges = definitions.flatMap((definition) => definition.edges.map(toEdge));
  const phases = nodes.filter((node) => node.type === "phase");
  const actions = new Map();
  for (const node of nodes.filter((item) => item.type === "platform_action" && item.config.action)) {
    const routes = edges.filter((edge) => edge.source === node.id && edge.when).map((edge) => edge.when);
    actions.set(node.config.action, [...new Set([...(actions.get(node.config.action) ?? []), ...routes])]);
  }
  return {
    agents: [...new Set(phases.map((node) => node.config.agent))].map((key) => ({ key, name: key, capability_ceiling: "deliver" })),
    tools: [...new Set(phases.flatMap((node) => [...(node.config.tool_policy?.allowlist ?? []),
      ...(node.config.workflow_contract?.source_steps ?? []).map((step) => step.tool)]))],
    checkTypes: [...new Set(phases.flatMap((node) => (node.config.workflow_contract?.checks ?? []).map((check) => check.type)))]
      .map((type) => ({ type, label: type, params: [] })),
    gateCheckTypes: GATE_CHECK_TYPES,
    workflows: [],
    platformActions: [...actions].map(([key, routes]) => ({ key, label: key, routes })),
    // The backend's own list (graph.py SUBJECT_*), as the server's catalog sends it; a hand-kept copy went stale
    // when readiness/decisions/interview were added.
    confirmationSubjects: BACKEND_SUBJECTS,
    watchConditions: ["pr.approved", "pr.merged", "pr.declined", "ci.succeeded", "ci.failed", "jira.status", "approval.decided"],
    outcomes: ["delivered", "done", "blocked", "stopped", "done_with_exception"],
    deciders: ["requester", "item_owner", "handoff_owner", "spec_origin", "role:reviewer"],
  };
}

const CATALOG = { ...catalogFor(SEEDS.map((seed) => seed.definition)),
  workflows: SEEDS.map((seed) => ({ key: seed.key, title: seed.name })) };
const box = (type, config = defaultConfig(type), extra = {}) => ({ id: `${type}1`, type, label: kindName(type), config, ...extra });
const paths = (issues) => issues.map((issue) => issue.path);

test("the shipped seed workflows have no problem in any box or arrow", () => {
  assert.ok(SEEDS.length >= 2);
  for (const seed of SEEDS) {
    const nodes = seed.definition.nodes.map(toNode);
    const edges = seed.definition.edges.map(toEdge);
    for (const node of nodes) assert.deepEqual(nodeConfigIssues(node, nodes, CATALOG), [], `${seed.key} ${node.id}`);
    for (const edge of edges) assert.deepEqual(edgeIssues(edge, edges, nodes, CATALOG), [], `${seed.key} ${edge.id}`);
  }
});

test("a new box starts as a draft whose missing parts are named at their field", () => {
  const issuesOf = (type) => paths(nodeConfigIssues(box(type), [], CATALOG));
  assert.deepEqual(issuesOf("phase"), ["config.agent", "config.workflow_contract.checks"]);
  assert.deepEqual(issuesOf("gate"), ["config.checks"]);
  assert.deepEqual(issuesOf("decision"), ["config.source"]);
  assert.deepEqual(issuesOf("user_conversation"), ["config.question"]);
  assert.deepEqual(issuesOf("watch"), ["config.conditions"]);
  assert.deepEqual(issuesOf("platform_action"), ["config.action"]);
  assert.deepEqual(issuesOf("sub_workflow"), ["config.workflow_key"]);
  for (const type of ["start", "outcome", "approval", "user_confirmation", "pause", "review"]) assert.deepEqual(issuesOf(type), [], type);
  assert.deepEqual(paths(nodeConfigIssues(box("start", {}, { label: " " }), [], CATALOG)), ["label"]);
});

test("phase rules: agent ceiling, write limits need protected tests for new files, no shell with limits", () => {
  const agent = { key: "reader", name: "Reader", capability_ceiling: "read_only" };
  const catalog = { ...CATALOG, agents: [...CATALOG.agents, agent], tools: [...CATALOG.tools, "bash"] };
  const phase = (contract, allowlist = []) => box("phase", { agent: "reader", tool_policy: { allowlist },
    workflow_contract: { workflow_id: "designer_step", workflow_class: "designer_step", capability_class: "change",
      source_steps: [{ tool: "bash" }], checks: [], ...contract } });
  const ceiling = nodeConfigIssues(phase({}), [], catalog);
  assert.deepEqual(paths(ceiling), ["config.workflow_contract.capability_class"]);
  assert.match(ceiling[0].message, /Reader may do at most: /);
  assert.ok(!/read_only/.test(ceiling[0].message), "no raw values in messages");
  const rules = nodeConfigIssues(phase({ capability_class: "read_only", path_rules: { write: ["src/**"], create: ["tests/**"] } }, ["bash"]), [], catalog);
  assert.deepEqual(paths(rules), ["config.workflow_contract.path_rules.create", "config.tool_policy.allowlist"]);
  assert.match(rules[1].message, /cannot use Bash/);
  const ok = nodeConfigIssues(phase({ capability_class: "read_only",
    path_rules: { write: ["src/**"], create: ["tests/**"], protect_confirmed_tests: true } }), [], catalog);
  assert.deepEqual(ok, []);
  const emptyStep = nodeConfigIssues(phase({ capability_class: "read_only", source_steps: [{ tool: "" }] }), [], catalog);
  assert.deepEqual(paths(emptyStep), ["config.workflow_contract.checks", "config.workflow_contract.source_steps.0.tool"]);
});

test("a condition branches only on results its box really has", () => {
  const gate = box("gate", { checks: [{ type: "tests_green" }] });
  const decision = (options) => box("decision", { source: "gate1", options });
  assert.deepEqual(nodeConfigIssues(decision(["passed"]), [gate], CATALOG), []);
  const wrong = nodeConfigIssues(decision(["passed", "approved"]), [gate], CATALOG);
  assert.deepEqual(paths(wrong), ["config.options"]);
  assert.match(wrong[0].message, /never ends with: Approved/);
  assert.deepEqual(routableSources([gate, box("phase"), box("outcome"), decision([])], "decision1", CATALOG).map((n) => n.id), ["gate1"]);
});

test("exit values follow the backend: fixed per kind, from the subject, the action, the options", () => {
  assert.deepEqual(exitValues(box("approval"), CATALOG), ["approved", "rejected"]);
  assert.equal(exitValues(box("phase"), CATALOG), null);
  assert.deepEqual(exitValues(box("user_confirmation", { subject: "functional_acceptance" }), CATALOG),
    ["accepted", "not_testable_yet", "rejected"]);
  assert.deepEqual(exitValues(box("watch", { conditions: ["pr.merged"] }), CATALOG), ["pr.merged"]);
  assert.deepEqual(exitValues(box("sub_workflow"), CATALOG), CATALOG.outcomes);
});

test("deciders and results are said in plain words", () => {
  assert.equal(deciderName("role:reviewer"), "Anyone with the role Reviewer");
  assert.equal(nodeConfigIssues(box("approval", { decider: "role:nobody" }), [], CATALOG)[0].path, "config.decider");
  for (const value of ["passed", "not_testable_yet", "pr.merged"]) assert.ok(!exitName(value).includes("_"), value);
  assert.equal(toolName("write_workspace_file"), "Write workspace file");
  assert.equal(paramName("tools"), "Which tools");
});

test("arrows: one per result, none for single-exit boxes, ways back are bounded", () => {
  const gate = box("gate", { checks: [{ type: "tests_green" }] });
  const phase = box("phase");
  const nodes = [gate, phase, box("outcome")];
  const arrow = (id, source, when, extra = {}) => ({ id, source, target: "outcome1", kind: "next", when, max_iterations: null, ...extra });
  const pass = arrow("a", "gate1", "passed");
  assert.deepEqual(edgeIssues(pass, [pass], nodes, CATALOG), []);
  assert.deepEqual(paths(edgeIssues(arrow("b", "gate1", null), [], nodes, CATALOG)), ["when"]);
  assert.deepEqual(paths(edgeIssues(arrow("c", "gate1", "passed"), [pass], nodes, CATALOG)), ["when"]);
  assert.deepEqual(paths(edgeIssues(arrow("d", "phase1", "passed"), [], nodes, CATALOG)), ["when"]);
  assert.deepEqual(paths(edgeIssues(arrow("e", "phase1", null), [arrow("f", "phase1", null)], nodes, CATALOG)), ["source"]);
  assert.deepEqual(paths(edgeIssues(arrow("g", "gate1", "failed", { kind: "loop" }), [], nodes, CATALOG)), ["max_iterations"]);
  assert.deepEqual(edgeIssues(arrow("h", "gate1", "failed", { kind: "loop", max_iterations: 3 }), [], nodes, CATALOG), []);
  assert.deepEqual(paths(edgeIssues(arrow("i", "gate1", "failed", { max_iterations: 3 }), [], nodes, CATALOG)), ["max_iterations"]);
});

test("patches carry the complete new config and never change the old one", () => {
  const before = defaultConfig("phase");
  const after = setIn(before, "workflow_contract.path_rules", { write: ["src/**"] });
  assert.deepEqual(after.workflow_contract.path_rules, { write: ["src/**"] });
  assert.equal(after.workflow_contract.capability_class, "read_only");
  assert.equal(before.workflow_contract.path_rules, undefined);
  assert.equal(after.tool_policy, before.tool_policy, "untouched branches are shared, not copied");
  const removed = setIn(after, "workflow_contract.path_rules", undefined);
  assert.ok(!("path_rules" in removed.workflow_contract));
});

test("a condition after an agent step branches on the step's possible results, with an otherwise", () => {
  const triage = box("phase", { ...defaultConfig("phase"), result_values: ["fix_needed", "no_fix"] }, { id: "triage" });
  const decision = box("decision", { source: "triage", options: ["fix_needed"] });
  assert.deepEqual(resultValues(triage, CATALOG), ["fix_needed", "no_fix"]);
  assert.equal(exitValues(triage, CATALOG), null, "the step itself keeps one way out");
  assert.deepEqual(routableSources([triage, box("phase")], "decision1", CATALOG).map((n) => n.id), ["triage"]);
  assert.deepEqual(nodeConfigIssues(decision, [triage], CATALOG), []);
  assert.deepEqual(exitValues(decision, CATALOG), ["fix_needed", OTHERWISE]);
  const nodes = [triage, decision, box("outcome")];
  const arrow = (id, when) => ({ id, source: "decision1", target: "outcome1", kind: "next", when, max_iterations: null });
  const fallback = arrow("o", OTHERWISE);
  assert.deepEqual(edgeIssues(fallback, [fallback], nodes, CATALOG), []);
  assert.deepEqual(paths(edgeIssues(arrow("o2", OTHERWISE), [fallback], nodes, CATALOG)), ["when"], "one otherwise only");
  assert.equal(exitName(OTHERWISE), "Otherwise");
  assert.deepEqual(paths(nodeConfigIssues(box("phase", { ...defaultConfig("phase"), result_values: ["a", "a"] }), [], CATALOG)),
    ["config.agent", "config.workflow_contract.checks", "config.result_values"]);
  assert.match(nodeConfigIssues(box("phase", { ...defaultConfig("phase"), agent: CATALOG.agents[0].key,
    workflow_contract: { workflow_id: "designer_step", workflow_class: "designer_step", capability_class: "read_only",
      checks: [{ type: CATALOG.checkTypes[0].type }] }, result_values: ["otherwise"] }), [], CATALOG)[0].message, /taken by conditions/);
});

test("a condition on a ticket field compares with a fixed operator and routes yes / otherwise", () => {
  const catalog = { ...CATALOG, workItemFields: [
    { key: "priority", label: "Priority", kind: "enum", values: ["High", "Low"] },
    { key: "labels", label: "Labels", kind: "list" }, { key: "points", label: "Story points", kind: "number" }] };
  const field = (config) => box("decision", { check: "field", ...config });
  assert.deepEqual(nodeConfigIssues(field({ field: "priority", operator: "is", value: "High" }), [], catalog), []);
  assert.deepEqual(exitValues(field({ field: "priority" }), catalog), ["yes", "no"]);
  assert.deepEqual(paths(nodeConfigIssues(field({ field: "", operator: "", value: "" }), [], catalog)), ["config.field"]);
  assert.deepEqual(paths(nodeConfigIssues(field({ field: "labels", operator: "greater_than", value: "" }), [], catalog)),
    ["config.operator", "config.value"]);
  assert.match(nodeConfigIssues(field({ field: "priority", operator: "is", value: "Urgent" }), [], catalog)[0].message, /never has this value/);
  assert.deepEqual(nodeConfigIssues(field({ field: "points", operator: "greater_than", value: 3 }), [], catalog), []);
  assert.deepEqual(paths(nodeConfigIssues(field({ field: "points", operator: "less_than", value: "3" }), [], catalog)), ["config.value"]);
  assert.equal(exitName("yes"), "Yes");
});

test("an agent step carries the technical name the backend requires", () => {
  const fresh = defaultConfig("phase");
  assert.equal(fresh.workflow_contract.workflow_id, DESIGNER_STEP_ID);
  assert.equal(fresh.workflow_contract.workflow_class, DESIGNER_STEP_ID);
  const old = box("phase", { agent: CATALOG.agents[0].key,
    workflow_contract: { capability_class: "read_only", checks: [{ type: CATALOG.checkTypes[0].type }] } });
  const issues = nodeConfigIssues(old, [], CATALOG);
  assert.deepEqual(paths(issues), ["config.workflow_contract.workflow_id", "config.workflow_contract.workflow_class"]);
  assert.ok(!/workflow_id|workflow_class/.test(issues[0].message), "said in plain words");
});

// on_open_high (backend auto_accept.py): unset waits; a wrong value or the key on another kind of box is said at the
// box, not only on save.
test("a confirmation's open-high setting names the default and refuses what the backend refuses", () => {
  assert.equal(onOpenHighChoices().empty, "Default (wait for a person)");
  assert.equal(onOpenHighSentence({ auto_revise: 2 }),
    "If a high finding is still open after the automatic revisions, the run waits for a person (default).");
  assert.equal(onOpenHighSentence({ on_open_high: "continue_with_findings" }),
    "If a high finding is still open after the automatic revisions, the run continues and the findings go on the pull request.");
  assert.equal(onOpenHighSentence({}), "");
  const catalog = { confirmationSubjects: ["decisions"] };
  const box = (type, config) => ({ id: "n", type, label: "Ship", config });
  const at = (issues) => issues.filter((issue) => issue.path === "config.on_open_high").map((issue) => issue.message);
  assert.deepEqual(at(nodeConfigIssues(box("user_confirmation", { subject: "decisions" }), [], catalog)), []);
  assert.deepEqual(at(nodeConfigIssues(box("user_confirmation", { subject: "decisions", on_open_high: "continue_with_findings" }), [], catalog)), []);
  assert.deepEqual(at(nodeConfigIssues(box("user_confirmation", { subject: "decisions", on_open_high: "skip" }), [], catalog)),
    ["Choose what happens when a high finding is still open."]);
  assert.equal(at(nodeConfigIssues(box("outcome", { outcome: "done", on_open_high: "wait" }), [], { ...catalog, outcomes: ["done"] })).length, 1);
});
