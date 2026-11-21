// The state of a workspace's Access section: the loaded payload, the editable drafts per kind (direct users, groups,
// global roles), loading, saving and the last error.
import { useEffect, useMemo, useState, type Dispatch, type SetStateAction } from "react";

import type { ReadJsonFn } from "../../hooks/useAdminTabLoader.types";
import type { AdminProjectAccessPayload, AdminProjectAccessUser } from "../../types/projectQualityTypes.access";
import {
  DEFAULT_PROJECT_ROLE,
  accessSavePayload,
  draftsFromPayload,
  newDraftKey,
  type AccessDrafts,
} from "./projectAccessDrafts";

const EMPTY_DRAFTS: AccessDrafts = { direct: [], groups: [], roles: [] };

export type DraftKind = keyof AccessDrafts;

function idOf(kind: DraftKind, row: Record<string, unknown>): string {
  const field = kind === "direct" ? "user_id" : kind === "groups" ? "group_id" : "role_id";
  return String(row[field] || "");
}

// The ids already chosen in the other rows of a kind, so each picker offers only the rest.
function usedIdsOf(drafts: AccessDrafts, kind: DraftKind, ignoreRowKey: string) {
  return new Set(
    (drafts[kind] as Array<Record<string, unknown>>)
      .filter((row) => row.key !== ignoreRowKey)
      .map((row) => idOf(kind, row))
      .filter(Boolean),
  );
}

// Edit, remove and add draft rows of one kind; a new row holds the default workspace role.
function draftRowActions(setDrafts: Dispatch<SetStateAction<AccessDrafts>>) {
  const updateRow = <K extends DraftKind>(kind: K, rowKey: string, patch: Partial<AccessDrafts[K][number]>) =>
    setDrafts((current) => ({
      ...current,
      [kind]: (current[kind] as Array<{ key: string }>).map((row) =>
        row.key === rowKey ? { ...row, ...patch } : row,
      ),
    }));

  const removeRow = (kind: DraftKind, rowKey: string) =>
    setDrafts((current) => ({
      ...current,
      [kind]: (current[kind] as Array<{ key: string }>).filter((row) => row.key !== rowKey),
    }));

  const addRow = (kind: DraftKind) =>
    setDrafts((current) => {
      const base = { key: newDraftKey(kind), project_roles: [DEFAULT_PROJECT_ROLE] };
      if (kind === "direct") return { ...current, direct: [...current.direct, { ...base, user_id: "" }] };
      if (kind === "groups") return { ...current, groups: [...current.groups, { ...base, group_id: "" }] };
      return { ...current, roles: [...current.roles, { ...base, role_id: "" }] };
    });

  return { updateRow, removeRow, addRow };
}

// Saves the drafts (PUT) and shows what the server stored.
async function putAccess({ projectId, accessUrl, drafts, readJson, applyPayload, setSaving, setError }: {
  projectId: string;
  accessUrl: string;
  drafts: AccessDrafts;
  readJson: ReadJsonFn;
  applyPayload: (next: AdminProjectAccessPayload) => void;
  setSaving: (saving: boolean) => void;
  setError: (error: string | null) => void;
}) {
  if (!projectId) return;
  setSaving(true);
  setError(null);
  try {
    applyPayload(
      await readJson<AdminProjectAccessPayload>(accessUrl, {
        method: "PUT",
        body: JSON.stringify(accessSavePayload(drafts)),
      }),
    );
  } catch (saveError) {
    setError(saveError instanceof Error ? saveError.message : "Failed to save workspace access.");
  } finally {
    setSaving(false);
  }
}

export function useProjectAccess(projectId: string, readJson: ReadJsonFn) {
  const accessUrl = `/admin/chat/api/panel/projects/${encodeURIComponent(projectId)}/access`;
  const [payload, setPayload] = useState<AdminProjectAccessPayload | null>(null);
  const [drafts, setDrafts] = useState<AccessDrafts>(EMPTY_DRAFTS);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const userById = useMemo(
    () =>
      (payload?.available_users || []).reduce<Record<string, AdminProjectAccessUser>>((acc, user) => {
        acc[user.id] = user;
        return acc;
      }, {}),
    [payload],
  );

  const usedIds = (kind: DraftKind, ignoreRowKey: string) => usedIdsOf(drafts, kind, ignoreRowKey);

  const applyPayload = (next: AdminProjectAccessPayload) => {
    setPayload(next);
    setDrafts(draftsFromPayload(next));
  };

  const loadAccess = async () => {
    if (!projectId) {
      setPayload(null);
      setDrafts(EMPTY_DRAFTS);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      applyPayload(await readJson<AdminProjectAccessPayload>(accessUrl));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load workspace access.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadAccess();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const { updateRow, removeRow, addRow } = draftRowActions(setDrafts);

  const saveAccess = () => putAccess({ projectId, accessUrl, drafts, readJson, applyPayload, setSaving, setError });

  return { payload, drafts, loading, saving, error, userById, usedIds, loadAccess, updateRow, removeRow, addRow, saveAccess };
}

export type ProjectAccessState = ReturnType<typeof useProjectAccess>;
