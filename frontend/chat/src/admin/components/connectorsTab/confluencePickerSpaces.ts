// The spaces the Confluence page picker shows (the second connection's pages could not be
// chosen). The page list (`confluence_allowed_pages`) belongs to the entry (global, or a Workspace's limits) and
// narrows every connection that serves it, so the picker shows the entry's allowed spaces *and* every space a named
// connection binds there, each read by the server with the connection that serves it. Pure: no requests, no React.
import type { NamedConnectionList } from "../namedConnections/namedConnectionsTypes";

export type PickerSpaces = {
  spaces: string[];
  // Space → the named connection that serves it (absent: the default connection).
  servedBy: Record<string, string>;
  // Some named connection serving a shown space passed its last test.
  namedTested: boolean;
};

/** The default's allowed spaces, then each named connection's bound spaces (a Workspace: its own, then the global
 * ones it does not override); a space bound by a named connection is labelled with that connection. */
export function pickerSpaces(allowed: string[], list: NamedConnectionList | null): PickerSpaces {
  const spaces: string[] = [];
  const servedBy: Record<string, string> = {};
  const seen = new Map<string, string>();
  const add = (key: string) => {
    const upper = key.toUpperCase();
    if (!seen.has(upper)) {
      seen.set(upper, key);
      spaces.push(key);
    }
    return seen.get(upper) as string;
  };
  allowed.forEach(add);
  let namedTested = false;
  const serving = [
    ...(list?.connections ?? []).map((connection) => ({ connection, keys: connection.boundScopes })),
    ...(list?.inherited ?? []).map((connection) => ({ connection, keys: connection.servedHere })),
  ];
  for (const { connection, keys } of serving) {
    for (const key of keys) {
      const shown = add(key);
      if (!(shown in servedBy)) servedBy[shown] = connection.name;
    }
    if (keys.length && connection.lastTest?.ok) namedTested = true;
  }
  return { spaces, servedBy, namedTested };
}
