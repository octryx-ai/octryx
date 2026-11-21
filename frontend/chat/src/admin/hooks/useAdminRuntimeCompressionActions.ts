import type { Dispatch, SetStateAction } from "react";
import type { AdminRuntime, AdminToolResultCompressionLog, AdminToolResultCompressor } from "../types/adminPanelTypes.runtimeCorp";

type ReadJsonFn = <T>(input: RequestInfo, init?: RequestInit) => Promise<T>;

type ToolCompressorActionArgs = {
  readJson: ReadJsonFn;
  toolResultCompressorDrafts: Record<
    string,
    { strategy: string; config: Record<string, unknown>; is_active: boolean }
  >;
  setToolResultCompressionSaving: Dispatch<SetStateAction<string | null>>;
  setToolResultCompressors: Dispatch<
    SetStateAction<AdminToolResultCompressor[]>
  >;
  setToolResultCompressorDrafts: Dispatch<
    SetStateAction<
      Record<
        string,
        {
          strategy: string;
          config: Record<string, unknown>;
          is_active: boolean;
        }
      >
    >
  >;
  setToolResultCompressionLogs: Dispatch<
    SetStateAction<AdminToolResultCompressionLog[]>
  >;
};

export function createHandleSaveToolResultCompressor({
  readJson,
  toolResultCompressorDrafts,
  setToolResultCompressionSaving,
  setToolResultCompressors,
  setToolResultCompressorDrafts,
  setToolResultCompressionLogs,
}: ToolCompressorActionArgs) {
  return async (toolName: string) => {
    const draft = toolResultCompressorDrafts[toolName];
    if (!draft) return;
    setToolResultCompressionSaving(toolName);
    try {
      const updated = await readJson<AdminToolResultCompressor>(
        `/admin/chat/api/panel/tool-result-compressors/${toolName}`,
        {
          method: "PUT",
          body: JSON.stringify({
            strategy: draft.strategy,
            config: draft.config,
            is_active: draft.is_active,
          }),
        },
      );
      setToolResultCompressors((prev) =>
        prev.map((item) => (item.tool_name === toolName ? updated : item)),
      );
      setToolResultCompressorDrafts((prev) => ({
        ...prev,
        [toolName]: {
          strategy: updated.strategy,
          config: updated.config || {},
          is_active: updated.is_active,
        },
      }));
      const logData = await readJson<AdminToolResultCompressionLog[]>(
        "/admin/chat/api/panel/tool-result-compression-log?limit=12",
      );
      setToolResultCompressionLogs(logData);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to save compressor");
    } finally {
      setToolResultCompressionSaving(null);
    }
  };
}

type RuntimeTagsActionArgs = {
  readJson: ReadJsonFn;
  runtimeTagsInput: string;
  setRuntimes: Dispatch<SetStateAction<AdminRuntime[]>>;
  setEditingRuntimeTags: Dispatch<SetStateAction<string | null>>;
};

export function createHandleSaveRuntimeTags({
  readJson,
  runtimeTagsInput,
  setRuntimes,
  setEditingRuntimeTags,
}: RuntimeTagsActionArgs) {
  return async (runtimeId: string) => {
    const tags = runtimeTagsInput
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean);
    const updated = await readJson<AdminRuntime>(
      `/admin/chat/api/panel/runtimes/${runtimeId}`,
      {
        method: "PUT",
        body: JSON.stringify({ use_case_tags: tags }),
      },
    );
    setRuntimes((prev) =>
      prev.map((item) => (item.id === updated.id ? updated : item)),
    );
    setEditingRuntimeTags(null);
  };
}
