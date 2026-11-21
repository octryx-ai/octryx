import { useCallback, useEffect, useState } from "react";

import type { ContentCategory } from "../providerTab/litellmGatewayApprovedCategories";
import { loadContentCategories } from "./contentCategories";
import { loadCatalog } from "./modelCatalogApi";
import { readCatalog } from "./modelCatalogContract";
import type { Catalog, CatalogScope, StatusFilter } from "./modelCatalogContract";

// The catalog with the content categories, the filters, the opened model and the sync drawer.
export function useModelCatalog() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [loadError, setLoadError] = useState("");
  const [categories, setCategories] = useState<ContentCategory[]>([]);
  const [providerId, setProviderId] = useState("");
  const [status, setStatus] = useState<StatusFilter>("");
  // The catalog opens on the used and enabled models; "All models" shows every one.
  const [scope, setScope] = useState<CatalogScope>("inUse");
  const [openId, setOpenId] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);

  const reload = useCallback(() => {
    loadCatalog()
      .then((payload) => {
        setCatalog(readCatalog(payload));
        setLoadError("");
      })
      .catch(() => setLoadError("The Model catalog could not be loaded (platform admin role required)."));
  }, []);

  useEffect(() => {
    reload();
    loadContentCategories().then(setCategories).catch(() => setCategories([]));
  }, [reload]);

  return { catalog, setCatalog, loadError, categories, providerId, setProviderId, status, setStatus, scope, setScope, openId, setOpenId, syncing, setSyncing, reload };
}
