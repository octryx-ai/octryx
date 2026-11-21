// Engineering Knowledge pack requests behind the admin hook's callbacks: refresh, build, delete and retrieval search.
import type {
  EngineeringKnowledgeBuildRun,
  EngineeringKnowledgePack,
  EngineeringKnowledgeRetrievalSearchPayload,
} from "../types/engineeringKnowledgeTypes";
import {
  engineeringKnowledgeBuildPayload,
  hasEngineeringKnowledgeTargetVersion,
} from "../components/engineeringKnowledgeBuildRequest";
import type { EngineeringKnowledgePackState } from "./engineeringKnowledgePackState";
import type { ReadJsonFn } from "./useAdminTabLoader.types";

type PacksPayload = {
  packs: EngineeringKnowledgePack[];
  total: number;
};

type BuildRunsPayload = {
  build_runs: EngineeringKnowledgeBuildRun[];
  total: number;
};

const BASE = "/admin/chat/api/panel/engineering-knowledge";
const errorText = (error: unknown, fallback: string) => (error instanceof Error ? error.message : fallback);

type S = EngineeringKnowledgePackState;
type Ctx<K extends keyof S> = Pick<S, K> & { readJson: ReadJsonFn };

export async function refreshPacks(
  state: Ctx<
    | "setEngineeringKnowledgeLoading" | "setEngineeringKnowledgeError" | "setEngineeringKnowledgePacks"
    | "setEngineeringKnowledgePackTotal" | "setEngineeringKnowledgeBuildRuns" | "setSelectedEngineeringKnowledgePack"
  > & { selectedId: string | undefined },
  loadDetail: (packId: string) => Promise<EngineeringKnowledgePack>,
) {
  state.setEngineeringKnowledgeLoading(true);
  state.setEngineeringKnowledgeError(null);
  try {
    const [packsPayload, buildRunsPayload] = await Promise.all([
      state.readJson<PacksPayload>(`${BASE}/packs`),
      state.readJson<BuildRunsPayload>(`${BASE}/build-runs?limit=10`),
    ]);
    state.setEngineeringKnowledgePacks(packsPayload.packs || []);
    state.setEngineeringKnowledgePackTotal(packsPayload.total || 0);
    state.setEngineeringKnowledgeBuildRuns(buildRunsPayload.build_runs || []);
    const selectedId = state.selectedId || packsPayload.packs?.[0]?.id;
    if (selectedId) {
      await loadDetail(selectedId);
    } else {
      state.setSelectedEngineeringKnowledgePack(null);
    }
  } catch (error) {
    state.setEngineeringKnowledgeError(errorText(error, "Engineering pack refresh failed"));
  } finally {
    state.setEngineeringKnowledgeLoading(false);
  }
}

export async function createBuildRun(
  state: Ctx<
    | "engineeringKnowledgeBuildVersions" | "engineeringKnowledgeAllowNetwork" | "setEngineeringKnowledgeError"
    | "setEngineeringKnowledgeBusy"
  >,
  refresh: () => Promise<void>,
  loadDetail: (packId: string) => Promise<EngineeringKnowledgePack>,
) {
  if (!hasEngineeringKnowledgeTargetVersion(state.engineeringKnowledgeBuildVersions)) {
    state.setEngineeringKnowledgeError("Enter at least one exact target version.");
    return;
  }
  state.setEngineeringKnowledgeBusy(true);
  state.setEngineeringKnowledgeError(null);
  try {
    const run = await state.readJson<EngineeringKnowledgeBuildRun>(`${BASE}/build-runs`, {
      method: "POST",
      body: JSON.stringify({
        ...engineeringKnowledgeBuildPayload(state.engineeringKnowledgeBuildVersions),
        allow_network: state.engineeringKnowledgeAllowNetwork,
      }),
    });
    await refresh();
    if (run.pack_id) {
      await loadDetail(run.pack_id);
    }
  } catch (error) {
    state.setEngineeringKnowledgeError(errorText(error, "Engineering pack build failed"));
  } finally {
    state.setEngineeringKnowledgeBusy(false);
  }
}

export async function deletePack(
  state: Ctx<"setEngineeringKnowledgeBusy" | "setEngineeringKnowledgeError" | "setSelectedEngineeringKnowledgePack"> & {
    selectedId: string | undefined;
  },
  refresh: () => Promise<void>,
  pack: EngineeringKnowledgePack,
) {
  if (!window.confirm(`Delete Engineering Pack "${pack.name}" and all of its versions?`)) {
    return;
  }
  state.setEngineeringKnowledgeBusy(true);
  state.setEngineeringKnowledgeError(null);
  try {
    await state.readJson(`${BASE}/packs/${encodeURIComponent(pack.id)}`, { method: "DELETE" });
    if (state.selectedId === pack.id) {
      state.setSelectedEngineeringKnowledgePack(null);
    }
    await refresh();
  } catch (error) {
    state.setEngineeringKnowledgeError(errorText(error, "Engineering pack deletion failed"));
  } finally {
    state.setEngineeringKnowledgeBusy(false);
  }
}

export async function searchRetrievalIndex(
  state: Ctx<
    "setEngineeringKnowledgeRetrievalLoading" | "setEngineeringKnowledgeError" | "setEngineeringKnowledgeRetrievalResults"
  >,
  versionId: string,
  query: string,
  recordKind: string,
) {
  state.setEngineeringKnowledgeRetrievalLoading(true);
  state.setEngineeringKnowledgeError(null);
  try {
    const params = new URLSearchParams();
    if (query.trim()) params.set("query", query.trim());
    if (recordKind.trim() && recordKind !== "all") {
      params.set("record_kind", recordKind.trim());
    }
    params.set("limit", "20");
    const payload = await state.readJson<EngineeringKnowledgeRetrievalSearchPayload>(
      `${BASE}/versions/${encodeURIComponent(versionId)}/retrieval-index?${params.toString()}`,
    );
    state.setEngineeringKnowledgeRetrievalResults((current) => ({ ...current, [versionId]: payload }));
    return payload;
  } catch (error) {
    state.setEngineeringKnowledgeError(errorText(error, "Engineering pack retrieval search failed"));
    throw error;
  } finally {
    state.setEngineeringKnowledgeRetrievalLoading(false);
  }
}
