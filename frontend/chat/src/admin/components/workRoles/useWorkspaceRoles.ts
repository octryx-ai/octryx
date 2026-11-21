import { useCallback, useEffect, useMemo, useState } from "react";
import type { Dispatch, SetStateAction } from "react";

import { readJson } from "../../utils/adminPanelHelpers";
import type { AdminProjectAccessPayload } from "../../types/projectQualityTypes.access";
import type { AssignMode, PickOption } from "./AssignPanel";
import { listSsoProviders, loadWorkspaceRoles, revokeAssignment, saveRoleBasedTools } from "./workRolesApi";
import { errorView, subjectLabel, type AssignmentRow, type ErrorView } from "./workRolesModel";
import type { SsoProvider, WorkspaceRoles } from "./workRolesTypes";

type Setter<T> = Dispatch<SetStateAction<T>>;

// Who can be previewed: the Workspace's members, the people holding a role and the members without one.
function peopleOf(access: AdminProjectAccessPayload | null, data: WorkspaceRoles | null): PickOption[] {
  const seen = new Map<string, string>();
  for (const user of access?.assignments ?? []) seen.set(user.user_id, user.display_name || user.username);
  for (const a of data?.assignments ?? []) if (a.is_active && a.subject.kind === "user") seen.set(a.subject.user_id, subjectLabel(a.subject));
  for (const m of data?.members_without_role ?? []) seen.set(m.user_id, m.label);
  return [...seen.entries()].map(([id, label]) => ({ id, label })).sort((a, b) => a.label.localeCompare(b.label));
}

// The section's state: the Workspace's roles, SSO providers, access listing and the open dialog or panel.
export function useWorkspaceRoles(workspaceId: string) {
  const [data, setData] = useState<WorkspaceRoles | null>(null);
  const [loadError, setLoadError] = useState<ErrorView | null>(null);
  const [error, setError] = useState<ErrorView | null>(null);
  const [providers, setProviders] = useState<SsoProvider[]>([]);
  const [access, setAccess] = useState<AdminProjectAccessPayload | null>(null);
  const [assign, setAssign] = useState<AssignMode | null>(null);
  const [switchStep, setSwitchStep] = useState<boolean | null>(null);
  const [switchError, setSwitchError] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<AssignmentRow | null>(null);
  const [revokeIds, setRevokeIds] = useState<string[]>([]);
  const [revokeError, setRevokeError] = useState<string | null>(null);
  const [preview, setPreview] = useState<PickOption | null>(null);
  const [previewPick, setPreviewPick] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      setData(await loadWorkspaceRoles(workspaceId));
    } catch (failure) {
      setData(null);
      setLoadError(errorView(failure, "The Workspace's roles could not be loaded."));
    }
  }, [workspaceId]);

  useEffect(() => {
    setData(null);
    setAccess(null);
    setPreviewPick("");
    void load();
    listSsoProviders().then(setProviders).catch(() => setProviders([]));
    readJson<AdminProjectAccessPayload>(`/admin/chat/api/panel/projects/${encodeURIComponent(workspaceId)}/access`)
      .then(setAccess).catch(() => setAccess(null));
  }, [workspaceId, load]);

  const people: PickOption[] = useMemo(() => peopleOf(access, data), [access, data]);
  const allUsers: PickOption[] = useMemo(() => {
    const list = (access?.available_users ?? []).filter((u) => u.is_active).map((u) => ({ id: u.id, label: u.display_name || u.username }));
    return list.length ? list : people;
  }, [access, people]);
  const groups: PickOption[] = useMemo(
    () => (access?.group_assignments ?? []).filter((g) => g.is_active).map((g) => ({ id: g.group_id, label: g.name })),
    [access],
  );
  return {
    data, setData, loadError, error, setError, providers, assign, setAssign, switchStep, setSwitchStep, switchError, setSwitchError,
    revoking, setRevoking, revokeIds, setRevokeIds, revokeError, setRevokeError, preview, setPreview, previewPick, setPreviewPick,
    busy, setBusy, load, people, allUsers, groups,
  };
}

export type WorkspaceRolesModel = ReturnType<typeof useWorkspaceRoles>;

/** A refusal in one line: the server's message, the setting it names and who can change it. */
const refusalLine = (view: ErrorView) =>
  [view.message, view.setting && `Setting: ${view.setting}`, view.whoCanChange && `Who can change it: ${view.whoCanChange}`].filter(Boolean).join(" ");

// A failed write: a version conflict closes the dialog and reloads; anything else stays in the dialog.
async function refused(m: WorkspaceRolesModel, failure: unknown, close: () => void, show: Setter<string | null>, line: (view: ErrorView) => string) {
  const view = errorView(failure);
  if (view.conflict) {
    close();
    m.setError(view);
    await m.load();
  } else show(line(view));
}

export async function applySwitch(m: WorkspaceRolesModel, workspaceId: string, data: WorkspaceRoles) {
  if (m.switchStep === null) return;
  m.setBusy(true);
  m.setSwitchError(null);
  try {
    const settings = await saveRoleBasedTools(workspaceId, m.switchStep, data.settings.version);
    m.setData({ ...data, settings });
    m.setSwitchStep(null);
  } catch (failure) {
    await refused(m, failure, () => m.setSwitchStep(null), m.setSwitchError, refusalLine);
  } finally {
    m.setBusy(false);
  }
}

export async function applyRevoke(m: WorkspaceRolesModel, workspaceId: string) {
  const { revoking, revokeIds } = m;
  if (!revoking) return;
  m.setBusy(true);
  m.setRevokeError(null);
  try {
    for (const assignment of revoking.assignments.filter((a) => revokeIds.includes(a.id))) await revokeAssignment(workspaceId, assignment);
    m.setRevoking(null);
    await m.load();
  } catch (failure) {
    await refused(m, failure, () => m.setRevoking(null), m.setRevokeError, (view) => view.message);
  } finally {
    m.setBusy(false);
  }
}
