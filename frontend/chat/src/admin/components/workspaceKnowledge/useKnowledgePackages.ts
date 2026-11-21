import { useCallback, useEffect, useState } from "react";

import { workspaceKnowledgeApi } from "./workspaceKnowledgeApi";
import type { KnowledgePackage } from "./workspaceKnowledgeTypes";

// The Workspace's knowledge packages, the selected one, the research inputs and the running action; `run` puts the
// package an action returns first and selects it.
export function useKnowledgePackages(workspaceId: string) {
  const [packages, setPackages] = useState<KnowledgePackage[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [topic, setTopic] = useState("");
  const [product, setProduct] = useState("");
  const [versions, setVersions] = useState("");
  const [instruction, setInstruction] = useState("");
  const [extractGraph, setExtractGraph] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const listing = await workspaceKnowledgeApi.packages(workspaceId);
      setPackages(listing.packages);
      setSelectedId((current) => current ?? listing.packages[0]?.id ?? null);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    }
  }, [workspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const run = async (label: string, action: () => Promise<KnowledgePackage>, note?: (pkg: KnowledgePackage) => string) => {
    setBusy(label);
    try {
      const updated = await action();
      setPackages((current) => [updated, ...current.filter((item) => item.id !== updated.id)]);
      setSelectedId(updated.id);
      setMessage(note ? note(updated) : null);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  };

  return {
    packages, selectedId, setSelectedId, topic, setTopic, product, setProduct, versions, setVersions, instruction, setInstruction,
    extractGraph, setExtractGraph, busy, message, run,
  };
}

export type KnowledgePackagesState = ReturnType<typeof useKnowledgePackages>;
