import { useCallback, useEffect, useState } from "react";

import {
  loadCatalog, loadDraftImpact, loadEngineStatus, loadPickerEntities, loadPolicies, loadSchema, loadVersion, loadVersions,
} from "./policyEngineApi";
import { readDraftImpact } from "./policyLifecycleModel";
import type { DraftImpact } from "./policyLifecycleModel";
import { readStatus } from "./policyEngineStatus";
import { readVersion, readVersions, refusalText } from "./policyEngineVersions";
import type { EngineStatus } from "./policyEngineStatus";
import type { PolicyVersion } from "./policyEngineVersions";
import { EMPTY_ENTITIES, readCatalog, readPickerEntities, readPolicyView } from "./policyCatalogModel";
import type { Catalog, PickerEntities, PolicyView } from "./policyCatalogModel";

const str = (value: unknown) => (typeof value === "string" ? value : "");

// Everything the Policies page reads: engine status, the per-policy view of the working version
// (plus the generated baseline on demand), the versions with the full working and published texts, the picker
// entities, the catalog and (for the Cedar editors) the schema.
export function usePoliciesData(showGenerated: boolean) {
  const [status, setStatus] = useState<EngineStatus | null>(null);
  const [policies, setPolicies] = useState<PolicyView | null>(null);
  const [versions, setVersions] = useState<PolicyVersion[]>([]);
  const [history, setHistory] = useState<unknown>(null);
  const [working, setWorking] = useState<PolicyVersion | null>(null);
  const [published, setPublished] = useState<PolicyVersion | null>(null);
  const [entities, setEntities] = useState<PickerEntities>(EMPTY_ENTITIES);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [schema, setSchema] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [generatedProblem, setGeneratedProblem] = useState<string | null>(null);
  const [loadingGenerated, setLoadingGenerated] = useState(false);
  const [draftImpact, setDraftImpact] = useState<DraftImpact | null>(null);

  const load = useCallback(async () => {
    try {
      const [rawStatus, rawPolicies, rawVersions] = await Promise.all([loadEngineStatus(), loadPolicies(false), loadVersions()]);
      const view = readPolicyView(rawPolicies);
      const listed = readVersions(rawVersions);
      const current = listed.find((item) => item.state === "published") ?? null;
      const open = view.version && view.version.state !== "published" ? view.version : null;
      const [full, edited, impact] = await Promise.all([
        current ? loadVersion(current.version).then(readVersion) : Promise.resolve(null),
        open ? loadVersion(open.version).then(readVersion) : Promise.resolve(null),
        // The draft shadow's numbers (informational; a refusal just shows none).
        open ? loadDraftImpact(open.version).then(readDraftImpact).catch(() => null) : Promise.resolve(null),
      ]);
      setStatus(readStatus(rawStatus));
      setPolicies((previous) => ({ ...view, generated: previous?.generated && previous.version?.digest === view.version?.digest ? previous.generated : null }));
      setVersions(listed);
      setHistory(rawVersions);
      setPublished(full);
      setWorking(edited);
      setDraftImpact(impact);
      setProblem(null);
    } catch (error) {
      setProblem(refusalText(error));
    }
  }, []);

  useEffect(() => {
    void load();
    void loadPickerEntities().then((raw) => setEntities(readPickerEntities(raw))).catch(() => setEntities(EMPTY_ENTITIES));
    void loadCatalog().then((raw) => setCatalog(readCatalog(raw))).catch(() => setCatalog(null));
  }, [load]);

  useEffect(() => {
    if (!showGenerated || !policies || policies.generated !== null || loadingGenerated) return;
    setLoadingGenerated(true);
    void loadPolicies(true).then((raw) => {
      const generated = readPolicyView(raw).generated ?? [];
      setPolicies((current) => (current ? { ...current, generated } : current));
    }).catch((error) => {
      setGeneratedProblem(refusalText(error));
      setPolicies((current) => (current ? { ...current, generated: [] } : current));
    }).finally(() => setLoadingGenerated(false));
  }, [showGenerated, policies, loadingGenerated]);

  const ensureSchema = useCallback(async () => {
    if (schema) return;
    try { setSchema(str(((await loadSchema()) as { schema?: unknown })?.schema)); } catch { /* the server validates on save */ }
  }, [schema]);

  return {
    status, setStatus, policies, versions, history, working, published, entities, catalog, schema, problem, generatedProblem,
    loadingGenerated, load, ensureSchema, draftImpact,
  };
}
