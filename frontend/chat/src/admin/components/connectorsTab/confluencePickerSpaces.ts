import type { NamedConnectionList } from "../namedConnections/namedConnectionsTypes";

export type PickerSpaces = {
  spaces: string[];
  servedBy: Record<string, string>;
  namedTested: boolean;
};

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
