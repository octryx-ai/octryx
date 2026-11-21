import { useEffect, useState } from "react";
import type { Dispatch, SetStateAction } from "react";

import { listConnections } from "../connections/connectionsApi";
import { createRole, deleteRole, loadRole, setRoleTrusted, updateRole } from "./workRolesApi";
import { errorView, KEPT_FUNCTIONS, type ErrorView } from "./workRolesModel";
import { roleDraft, roleDraftProblems, roleWriteBody } from "./workRoleDraft";
import type { RoleDraft, WorkRole } from "./workRolesTypes";

type Setter<T> = Dispatch<SetStateAction<T>>;
export type TrustedStep = null | { on: boolean; reason: string };

/** A refusal in one line: the server's message, the setting it names and who can change it. */
function refusalLine(view: ErrorView): string {
  return [view.message, view.setting && `Setting: ${view.setting}`, view.whoCanChange && `Who can change it: ${view.whoCanChange}`]
    .filter(Boolean).join(" ");
}

type Ctx = {
  role: WorkRole | null; draft: RoleDraft; creating: boolean; trustedStep: TrustedStep;
  onSaved: (role: WorkRole | null) => void; onClose: () => void; fail: (failure: unknown) => Promise<void>;
  setBusy: Setter<boolean>; setError: Setter<ErrorView | null>; setRole: Setter<WorkRole | null>; setTrustedStep: Setter<TrustedStep>;
  setTrustedError: Setter<string | null>; setConfirmDelete: Setter<boolean>; setDeleteError: Setter<string | null>;
};

async function saveRole(ctx: Ctx) {
  ctx.setBusy(true);
  ctx.setError(null);
  try {
    const body = roleWriteBody(ctx.draft, ctx.role);
    const saved = ctx.creating ? await createRole(body) : await updateRole(ctx.role!.id, body);
    ctx.onSaved(saved);
    ctx.onClose();
  } catch (failure) {
    await ctx.fail(failure);
  } finally {
    ctx.setBusy(false);
  }
}

async function applyTrusted(ctx: Ctx) {
  const { role, trustedStep } = ctx;
  if (!role || !trustedStep) return;
  ctx.setBusy(true);
  ctx.setTrustedError(null);
  try {
    const saved = await setRoleTrusted(role.id, trustedStep.on, trustedStep.reason.trim(), role.version);
    ctx.setRole(saved);
    ctx.setTrustedStep(null);
    ctx.onSaved(saved);
  } catch (failure) {
    const view = errorView(failure);
    if (view.conflict) {
      ctx.setTrustedStep(null);
      await ctx.fail(failure);
    } else {
      ctx.setTrustedError(refusalLine(view));
    }
  } finally {
    ctx.setBusy(false);
  }
}

async function removeRole(ctx: Ctx) {
  if (!ctx.role) return;
  ctx.setBusy(true);
  ctx.setDeleteError(null);
  try {
    await deleteRole(ctx.role.id);
    ctx.setConfirmDelete(false);
    ctx.onSaved(null);
    ctx.onClose();
  } catch (failure) {
    // 409 role_built_in / role_in_use: the server's sentence, verbatim.
    ctx.setDeleteError(refusalLine(errorView(failure, "The role could not be deleted.")));
  } finally {
    ctx.setBusy(false);
  }
}

// The role editor's state and actions. Trusted has its own endpoint and is never part of Save.
export function useRoleEditor(initial: WorkRole | null, defaultWorkspaceId: string | null, onClose: () => void, onSaved: (role: WorkRole | null) => void) {
  const creating = initial === null;
  const [role, setRole] = useState<WorkRole | null>(initial);
  const [draft, setDraft] = useState<RoleDraft>(() => roleDraft(initial, defaultWorkspaceId));
  const [keyTouched, setKeyTouched] = useState(false);
  const [connections, setConnections] = useState<Array<{ id: string; name: string }> | null>(null);
  const [error, setError] = useState<ErrorView | null>(null);
  const [busy, setBusy] = useState(false);
  const [trustedStep, setTrustedStep] = useState<TrustedStep>(null);
  const [trustedError, setTrustedError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void listConnections().then((result) => {
      if (!cancelled) setConnections(result.kind === "ok" ? result.connections.map((c) => ({ id: c.id, name: c.name })) : []);
    });
    return () => { cancelled = true; };
  }, []);

  const set = (patch: Partial<RoleDraft>) => setDraft((current) => ({ ...current, ...patch }));
  const reload = async (id: string) => {
    const fresh = await loadRole(id);
    setRole(fresh);
    setDraft(roleDraft(fresh));
    return fresh;
  };
  const fail = async (failure: unknown) => {
    const view = errorView(failure);
    setError(view);
    if (view.conflict && role) await reload(role.id).catch(() => undefined);
  };
  const ctx: Ctx = {
    role, draft, creating, trustedStep, onSaved, onClose, fail, setBusy, setError, setRole, setTrustedStep, setTrustedError,
    setConfirmDelete, setDeleteError,
  };
  const toggle = (field: "function_keys" | "connection_ids") => (id: string, on: boolean) =>
    set({ [field]: on ? [...draft[field].filter((k) => k !== id), id] : draft[field].filter((k) => k !== id) });
  return {
    creating, role, draft, set, keyTouched, setKeyTouched, connections, error, busy, trustedStep, setTrustedStep, trustedError, setTrustedError,
    confirmDelete, setConfirmDelete, deleteError, setDeleteError,
    problems: roleDraftProblems(draft, creating), kept: role?.built_in ? KEPT_FUNCTIONS[role.key] ?? [] : [],
    save: () => saveRole(ctx), applyTrusted: () => applyTrusted(ctx), remove: () => removeRole(ctx),
    toggleFunction: toggle("function_keys"), toggleConnection: toggle("connection_ids"),
  };
}

export type RoleEditor = ReturnType<typeof useRoleEditor>;
