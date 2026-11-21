import { useEffect, useState } from "react";

import { readJson } from "../chatApiClient";

// A read-only part of a run the card shows next to the run itself (its events, its screenshots). Reloaded whenever
// `refreshKey` changes (the run's updated_at); a failed read shows nothing instead of an error, the run card stays.
export function useRunResource<T>(path: string | null, refreshKey: unknown): T | null {
  const [loaded, setLoaded] = useState<{ path: string | null; value: T | null }>({ path: null, value: null });
  useEffect(() => {
    if (!path) return;
    let current = true;
    readJson<T>(path)
      .then((value) => {
        if (current) setLoaded({ path, value });
      })
      .catch(() => {
        if (current) setLoaded({ path, value: null });
      });
    return () => {
      current = false;
    };
  }, [path, refreshKey]);
  return loaded.path === path ? loaded.value : null;
}
