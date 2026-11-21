// The essentials of one Workspace for its side panel on Admin › Workspaces, read from endpoints
// that exist today: the access assignments (members and their roles, groups), the Workspace's Knowledge sources and
// the connections available in it. Pure: no React, so tests can check the wording.

export type WorkspaceGlance = {
  members: string;
  sources: string;
  connections: string;
};

type Access = { assignments?: unknown; group_assignments?: unknown; role_assignments?: unknown } | null;
type Source = { state?: unknown; last_run?: { state?: unknown } | null };
type Connection = { name?: unknown; type?: unknown };

const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const plural = (count: number, one: string, many = `${one}s`) => `${count} ${count === 1 ? one : many}`;
const roleWord = (role: string) => role.charAt(0).toUpperCase() + role.slice(1).replace(/_/g, " ");

/** "3 people · 1 Owner, 2 Member · 1 group"; null access → "—" (the server did not answer). */
export function membersText(access: Access): string {
  if (!access) return "—";
  const people = list(access.assignments) as Array<{ project_role?: unknown; project_roles?: unknown }>;
  const groups = list(access.group_assignments).length;
  const byRole = new Map<string, number>();
  for (const person of people) {
    const roles = list(person.project_roles).filter((role): role is string => typeof role === "string");
    const role = roles[0] ?? (typeof person.project_role === "string" ? person.project_role : "");
    if (role) byRole.set(role, (byRole.get(role) ?? 0) + 1);
  }
  const parts = [plural(people.length, "person", "people")];
  if (byRole.size) parts.push(Array.from(byRole, ([role, count]) => `${count} ${roleWord(role)}`).join(", "));
  if (groups) parts.push(plural(groups, "group"));
  return parts.join(" · ");
}

/** "4 sources · 3 synced · 1 paused"; null → "—". */
export function sourcesText(sources: Source[] | null): string {
  if (!sources) return "—";
  if (!sources.length) return "No sources yet";
  const synced = sources.filter((source) => source.last_run?.state === "completed").length;
  const paused = sources.filter((source) => source.state === "paused").length;
  return [plural(sources.length, "source"), `${synced} synced`, ...(paused ? [`${paused} paused`] : [])].join(" · ");
}

/** "2 available: Jira Cloud, Bitbucket Shop" (names, at most five); null → "—". */
export function connectionsText(connections: Connection[] | null): string {
  if (!connections) return "—";
  if (!connections.length) return "None available";
  const names = connections.map((connection) => String(connection.name || connection.type || "")).filter(Boolean);
  const shown = names.slice(0, 5).join(", ");
  return `${connections.length} available${shown ? `: ${shown}${names.length > 5 ? ", …" : ""}` : ""}`;
}

export function workspaceGlance(access: Access, sources: Source[] | null, connections: Connection[] | null): WorkspaceGlance {
  return { members: membersText(access), sources: sourcesText(sources), connections: connectionsText(connections) };
}
