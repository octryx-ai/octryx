import { useEffect, useState } from "react";
import { DEFAULT_SOURCE_LIMIT } from "../../admin/components/workspaceKnowledge/workspaceKnowledgeRequest";
import { webSearchApi, workspaceKnowledgeApi } from "../../admin/components/workspaceKnowledge/workspaceKnowledgeApi";
import type { SourceListing, WebSearchOverview } from "../../admin/components/workspaceKnowledge/workspaceKnowledgeTypes";
import { connectorsApi } from "../../admin/components/workspaceKnowledge/connectorsApi";
import type { ConnectorListing } from "./knowledgeEntryStatus";

export type EntryLoaders = {
  sources: (workspaceId: string, page: { limit?: number }) => Promise<SourceListing>;
  connectors: (workspaceId: string) => Promise<ConnectorListing>;
  research: (workspaceId: string) => Promise<WebSearchOverview>;
};

const DEFAULT_LOADERS: EntryLoaders = {
  sources: workspaceKnowledgeApi.sourcePage, connectors: connectorsApi.list, research: webSearchApi.overview,
};

export type EntryOverview = {
  workspaceId: string;
  listing: SourceListing | null;
  sourcesFailed: boolean;
  connectors: ConnectorListing | null;
  connectorsFailed: boolean;
  research: WebSearchOverview | null;
  researchFailed: boolean;
};

const empty = (workspaceId: string): EntryOverview => ({
  workspaceId, listing: null, sourcesFailed: false, connectors: null, connectorsFailed: false, research: null,
  researchFailed: false,
});

// Reads the three existing workspace APIs once per workspace visit. A late answer from a previous
// workspace is ignored, and each read fails on its own so one outage never hides the other facts.
export function useKnowledgeEntryOverview(workspaceId: string, loaders: EntryLoaders = DEFAULT_LOADERS): EntryOverview {
  const [state, setState] = useState<EntryOverview>(() => empty(workspaceId));
  useEffect(() => {
    let active = true;
    setState(empty(workspaceId));
    const update = (patch: Partial<EntryOverview>) => {
      if (active) setState((current) => (current.workspaceId === workspaceId ? { ...current, ...patch } : current));
    };
    loaders.sources(workspaceId, { limit: DEFAULT_SOURCE_LIMIT }).then(
      (listing) => update({ listing }), () => update({ sourcesFailed: true }),
    );
    loaders.connectors(workspaceId).then(
      (connectors) => update({ connectors }), () => update({ connectorsFailed: true }),
    );
    loaders.research(workspaceId).then(
      (research) => update({ research }), () => update({ researchFailed: true }),
    );
    return () => { active = false; };
  }, [workspaceId, loaders]);
  return state.workspaceId === workspaceId ? state : empty(workspaceId);
}
