import { useEffect, useState } from "react";

import { NAMED_DESCRIPTORS_URL } from "./namedConnectionsTypes";
import { parseNamedDescriptors } from "./namedConnectionsParse";
import type { NamedDescriptor } from "./namedConnectionsTypes";

type ReadJson = <T = unknown>(url: string, init?: RequestInit) => Promise<T>;

let loaded: Promise<Record<string, NamedDescriptor>> | null = null;

// The connector types with named connections, from the server's descriptor registry: read once per page and
// shared by every connector card, so no card names a connector type itself. A failed read shows no named
// connections (null until known, {} on failure).
export function useNamedDescriptors(readJson: ReadJson | undefined | null): Record<string, NamedDescriptor> | null {
  const [registry, setRegistry] = useState<Record<string, NamedDescriptor> | null>(null);
  useEffect(() => {
    if (!readJson) return;
    let alive = true;
    loaded = loaded ?? readJson(NAMED_DESCRIPTORS_URL).then(parseNamedDescriptors, () => {
      loaded = null; // retried on the next mount
      return {};
    });
    void loaded.then((value) => {
      if (alive) setRegistry(value);
    });
    return () => {
      alive = false;
    };
  }, [readJson]);
  return registry;
}
