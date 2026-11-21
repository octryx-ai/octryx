import { useCallback, useEffect, useState } from "react";
import { namedConnectionsUrl, parseNamedConnections } from "../namedConnections/namedConnectionsParse";
import type { NamedConnectionList } from "../namedConnections/namedConnectionsTypes";
import { pickerSpaces } from "./confluencePickerSpaces";
import type { ReadJson } from "./confluencePageTreeApi";

/** The picker's spaces over the saved named Confluence connections of the global entry (projectId null) or a
 * Workspace; `reload` reads them again (the picker opens with the connections as saved now). */
export function useConfluencePickerSpaces(readJson: ReadJson | null, projectId: string | null, allowed: string[]) {
  const [list, setList] = useState<NamedConnectionList | null>(null);
  const reload = useCallback(async () => {
    if (!readJson) return;
    try {
      setList(parseNamedConnections(await readJson(namedConnectionsUrl(projectId, "confluence"))));
    } catch {
      setList(null); // without the list the picker shows the allowed spaces only
    }
  }, [readJson, projectId]);
  useEffect(() => { void reload(); }, [reload]);
  return { ...pickerSpaces(allowed, list), reload };
}
