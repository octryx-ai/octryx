import { useState } from "react";

import { readJson } from "../../utils/adminPanelHelpers";
import { readKnownValues } from "./serviceNowGroupsModel";
import type { KnownValues } from "./serviceNowGroupsModel";

/** Known groups and services of recent ServiceNow records from `url`, read on demand (read-only suggestions). */
export function useKnownValues(url: string) {
  const [known, setKnown] = useState<KnownValues | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "failed">("idle");
  const load = async () => {
    setState("loading");
    try {
      const read = readKnownValues(await readJson<unknown>(url));
      setKnown(read);
      setState(read ? "idle" : "failed");
    } catch {
      setState("failed");
    }
  };
  return { known, state, load };
}
