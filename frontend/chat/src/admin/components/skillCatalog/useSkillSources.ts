import { useCallback, useEffect, useState } from "react";

import { loadSources } from "./skillCatalogApi";
import { refusalText } from "./skillCatalogModel";
import type { CatalogSettings, SourceRow } from "./skillDeliveryTypes";

// The sources with the catalog settings, the source being edited and the last check; `check` runs one check and
// reloads the sources and the catalog.
export function useSkillSources(onChanged: () => void | Promise<void>) {
  const [sources, setSources] = useState<SourceRow[] | null>(null);
  const [settings, setSettings] = useState<CatalogSettings | null>(null);
  const [editing, setEditing] = useState<SourceRow | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ text: string; problem: boolean } | null>(null);

  const load = useCallback(async () => {
    try {
      const raw = (await loadSources()) as { sources: SourceRow[]; settings: CatalogSettings };
      setSources(raw.sources);
      setSettings(raw.settings);
    } catch (error) {
      setMessage({ text: refusalText(error), problem: true });
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const check = async (action: () => Promise<unknown>, describe: (raw: unknown) => string) => {
    setBusy(true);
    setMessage(null);
    try {
      const raw = await action();
      setMessage({ text: describe(raw), problem: false });
      await Promise.all([load(), onChanged()]);
    } catch (error) {
      setMessage({ text: refusalText(error), problem: true });
    } finally {
      setBusy(false);
    }
  };

  return { sources, settings, setSettings, editing, setEditing, busy, message, load, check };
}
