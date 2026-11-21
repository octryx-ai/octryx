import { useCallback, useEffect, useMemo, useState } from "react";

import type { ReadJsonFn } from "./useAdminTabLoader.types";
import type {
  WorkspaceAssignmentControlsUpdatePayload,
  WorkspaceBindingUpdatePayload,
  WorkspaceCompositionPayload,
  WorkspacePolicyUpdatePayload,
} from "../types/workspaceCompositionTypes";

export function useAdminWorkspaceComposition({ workspaceId, readJson }: {
  workspaceId: string | null | undefined;
  readJson: ReadJsonFn;
}) {
  const [payload, setPayload] = useState<WorkspaceCompositionPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savingBindingId, setSavingBindingId] = useState<string | null>(null);
  const [savingPolicy, setSavingPolicy] = useState(false);
  const [savingAssignmentControls, setSavingAssignmentControls] = useState(false);

  const reload = useCallback(
    async () => loadComposition(workspaceId, { readJson, setPayload, setError, setLoading }),
    [readJson, workspaceId],
  );

  useEffect(() => {
    void reload();
  }, [reload]);

  const updateBinding = useCallback(
    async (bindingId: string, patch: WorkspaceBindingUpdatePayload) => {
      if (!workspaceId) return null;
      return putComposition({
        readJson, setPayload, setError, busy: (on) => setSavingBindingId(on ? bindingId : null),
        path: () => `/admin/chat/api/panel/projects/${encodeURIComponent(workspaceId)}/workspace-composition/bindings/${encodeURIComponent(bindingId)}`,
        patch, failure: "Failed to update workspace binding.",
      });
    }, [readJson, workspaceId]);

  const updatePolicy = useCallback(
    async (patch: WorkspacePolicyUpdatePayload) => {
      if (!workspaceId) return null;
      return putComposition({
        readJson, setPayload, setError, busy: setSavingPolicy,
        path: () => `/admin/chat/api/panel/projects/${encodeURIComponent(workspaceId)}/workspace-composition/policy`,
        patch, failure: "Failed to update workspace policy.",
      });
    }, [readJson, workspaceId]);

  const updateAssignmentControls = useCallback(
    async (patch: WorkspaceAssignmentControlsUpdatePayload) => {
      if (!workspaceId) return null;
      return putComposition({
        readJson, setPayload, setError, busy: setSavingAssignmentControls,
        path: () => `/admin/chat/api/panel/projects/${encodeURIComponent(workspaceId)}/workspace-composition/assignment-controls`,
        patch, failure: "Failed to update workspace assignment controls.",
      });
    }, [readJson, workspaceId]);

  const bindingsByKind = useMemo(() => groupBindingsByKind(payload), [payload]);

  return {
    payload, loading, error, bindingsByKind, reload, savingBindingId, savingPolicy, savingAssignmentControls,
    updateBinding, updatePolicy, updateAssignmentControls,
  };
}

// One change saved: busy while it runs, the answer replaces the composition, a failure shows its message.
async function putComposition({ readJson, setPayload, setError, busy, path, patch, failure }: {
  readJson: ReadJsonFn;
  setPayload: (next: WorkspaceCompositionPayload) => void;
  setError: (error: string | null) => void;
  busy: (on: boolean) => void;
  path: () => string;
  patch: unknown;
  failure: string;
}) {
  busy(true);
  setError(null);
  try {
    const next = await readJson<WorkspaceCompositionPayload>(path(), {
      method: "PUT",
      body: JSON.stringify(patch),
    });
    setPayload(next);
    return next;
  } catch (updateError) {
    setError(updateError instanceof Error ? updateError.message : failure);
    return null;
  } finally {
    busy(false);
  }
}

async function loadComposition(workspaceId: string | null | undefined, { readJson, setPayload, setError, setLoading }: {
  readJson: ReadJsonFn;
  setPayload: (next: WorkspaceCompositionPayload | null) => void;
  setError: (error: string | null) => void;
  setLoading: (loading: boolean) => void;
}) {
  if (!workspaceId) {
    setPayload(null);
    setError(null);
    return null;
  }
  setLoading(true);
  setError(null);
  try {
    const next = await readJson<WorkspaceCompositionPayload>(
      `/admin/chat/api/panel/projects/${encodeURIComponent(workspaceId)}/workspace-composition`,
    );
    setPayload(next);
    return next;
  } catch (loadError) {
    setError(loadError instanceof Error ? loadError.message : "Failed to load workspace composition.");
    return null;
  } finally {
    setLoading(false);
  }
}

// The bindings grouped by capability kind, kinds in alphabetical order.
function groupBindingsByKind(payload: WorkspaceCompositionPayload | null) {
  const grouped = new Map<string, WorkspaceCompositionPayload["bindings"]>();
  for (const binding of payload?.bindings || []) {
    const current = grouped.get(binding.capability_kind) || [];
    current.push(binding);
    grouped.set(binding.capability_kind, current);
  }
  return Array.from(grouped.entries()).sort(([left], [right]) => left.localeCompare(right));
}
