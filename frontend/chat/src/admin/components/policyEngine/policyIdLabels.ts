// Readable labels for policy ids: a decision names its determining policies by id
// (`workspace:<uuid>:tool-rule:<rule>`, `platform:client-tool-permit`, a custom policy's `@id`). The UI shows the
// Workspace's name, the rule and the custom policy's `@name`; the raw id stays on hover and copy.

export type PolicyNames = { workspaces: Record<string, string>; policies: Record<string, string> };

export const NO_POLICY_NAMES: PolicyNames = { workspaces: {}, policies: {} };

const words = (slug: string) => slug.replace(/[-_]+/g, " ").trim();

const WORKSPACE_KINDS: Record<string, string> = {
  "command-unparseable": "Workspace rule: commands that could not be parsed",
  "model-denied": "Model policy: denied models",
  "model-granted": "Model policy: allowed models",
  "model-allow-all": "Model policy: all admitted models",
};

/** The Workspace's name, or a short id when it is unknown (deleted, or the names are not loaded). */
export const workspaceLabel = (id: string, names: PolicyNames) => names.workspaces[id] || `Workspace ${id.slice(0, 8)}${id.length > 8 ? "…" : ""}`;

function workspacePolicy(rest: string, names: PolicyNames): string {
  const [workspaceId, kind = "", ...tail] = rest.split(":");
  const workspace = workspaceLabel(workspaceId, names);
  const detail = tail.join(":");
  if (kind === "tool-rule" && detail) return `${workspace} · Workspace rule: ${words(detail)}`;
  if (kind === "client-deny" && detail) return `${workspace} · Claude Code deny rule ${detail}`;
  return `${workspace} · ${WORKSPACE_KINDS[kind] ?? words([kind, ...tail].join(" "))}`;
}

function classificationPolicy(rest: string): string {
  const [level, ...tail] = rest.split(":");
  if (tail[0] === "connector" && tail.length === 3) {
    return `Classification (${level}): ${tail[1]} connector ${tail[2] === "none" ? "blocked" : words(tail[2])}`;
  }
  return `Classification (${level}): ${words(tail.join(" "))}`;
}

/** One determining policy id as a label for people. */
export function policyIdLabel(id: string, names: PolicyNames = NO_POLICY_NAMES): string {
  const colon = id.indexOf(":");
  const prefix = colon > 0 ? id.slice(0, colon) : "";
  const rest = id.slice(colon + 1);
  if (prefix === "platform" && rest) return `Platform: ${words(rest)}`;
  if (prefix === "workspace" && rest) return workspacePolicy(rest, names);
  if (prefix === "classification" && rest.includes(":")) return classificationPolicy(rest);
  return names.policies[id] || id;
}
