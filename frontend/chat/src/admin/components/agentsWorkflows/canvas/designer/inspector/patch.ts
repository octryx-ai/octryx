// Pure helpers of the side panel, kept out of the .tsx forms so unit tests can load them: building a node's complete
// new config, and the backend's arrow rules (workflow_runs/graph.py route and loop checks) in plain words.
import type { DefEdge, DefNode, DesignerCatalog, FieldIssue } from "../types";
import { exitValues } from "./exitValues";
import { exitName } from "./labels";

type Config = Record<string, unknown>;
const record = (value: unknown): Config =>
  value && typeof value === "object" && !Array.isArray(value) ? (value as Config) : {};

/** The problems at ``path`` and below it. */
export const issuesAt = (issues: FieldIssue[], path: string) =>
  issues.filter((issue) => issue.path === path || issue.path.startsWith(`${path}.`));

/** ``config`` with ``value`` at ``path`` (dot-separated); ``undefined`` removes the key. Never mutates. */
export function setIn(config: Config, path: string, value: unknown): Config {
  const [head, ...rest] = path.split(".");
  const next = { ...config };
  if (!rest.length) {
    if (value === undefined) delete next[head];
    else next[head] = value;
    return next;
  }
  next[head] = setIn(record(config[head]), rest.join("."), value);
  return next;
}

// A workflow runs one box at a time: two arrows for the same way out are a fork the engine does not run. Teamwork
// work that should run side by side goes into a Parallel work box (split at run time by the coordinator's plan).
export const PARALLEL_HINT = "A workflow runs one box at a time; to let several agents work side by side, use a Parallel work box.";

/** The results an arrow out of ``source`` can stand for; null: the box has one way out, no choice. */
export function edgeChoices(source: DefNode | undefined, catalog: DesignerCatalog): string[] | null {
  return source ? exitValues(source, catalog) : null;
}

/** What the backend would refuse about one arrow, at its field ("when", "max_iterations"). */
export function edgeIssues(edge: DefEdge, edges: DefEdge[], nodes: DefNode[], catalog: DesignerCatalog): FieldIssue[] {
  const issues: FieldIssue[] = [];
  const source = nodes.find((node) => node.id === edge.source);
  const choices = edgeChoices(source, catalog);
  if (source?.type === "outcome") issues.push({ path: "source", message: "An end has no way out. Remove this arrow." });
  if (choices === null && edge.when !== null)
    issues.push({ path: "when", message: "This box has only one way out; the arrow needs no result." });
  if (choices !== null && source?.type !== "outcome") {
    // A condition's arrows are set in its own form (one row per result); here only the plain words differ.
    if (edge.when === null) issues.push({ path: "when", message: "Choose for which result this arrow is taken." });
    else if (!choices.includes(edge.when))
      issues.push({ path: "when", message: `${source?.label || "That box"} never ends with: ${exitName(edge.when)}.` });
    else if (edges.some((other) => other.id !== edge.id && other.source === edge.source && other.when === edge.when))
      issues.push({ path: "when", message: `Another arrow already leaves for “${exitName(edge.when)}”. ${PARALLEL_HINT}` });
  }
  if (choices === null && edges.some((other) => other.id !== edge.id && other.source === edge.source))
    issues.push({ path: "source", message: `${source?.label || "This box"} has only one way out; remove the extra arrow. ${PARALLEL_HINT}` });
  if (edge.kind === "loop" && (edge.max_iterations === null || edge.max_iterations < 1))
    issues.push({ path: "max_iterations", message: "Say how often at most the run may go back (at least once)." });
  if (edge.kind === "next" && edge.max_iterations !== null)
    issues.push({ path: "max_iterations", message: "Only a way back has a maximum." });
  return issues;
}
