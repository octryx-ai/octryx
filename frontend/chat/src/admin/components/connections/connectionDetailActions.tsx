// The actions of one connection's panel: save (confirmed when it binds the first keys or unbinds all), test and delete.
import type { useConfirmAction } from "../confirm/useConfirmAction";
import type { FieldErrors } from "./ConnectionFields";
import { bindsFirstKeys, boundScopesErrorText, firstBindingText, keysLeftOut, unbindsAll, unbindText, type UnboundToday } from "./boundScopes";
import { deleteConnection, loadConnection, resetDeviation, testConnection, updateConnection } from "./connectionsApi";
import { draftOf, type ConnectionDraft } from "./connectionDraft";
import { scopeKeyOf, type Binding, type ConnectionType } from "./connectionTypes";
import type { ConnectionDetail, TestResult } from "./connectionsModel";

export type ConnectionDetailDeps = {
  id: string;
  types: ConnectionType[];
  detail: ConnectionDetail | null | undefined;
  changes: Record<string, unknown>;
  dirty: boolean;
  keysProblem: string;
  binding: Binding | null;
  unboundToday: UnboundToday | null;
  confirm: ReturnType<typeof useConfirmAction>;
  load: () => Promise<void>;
  onChanged: () => void;
  onDeleted?: () => void;
  setBusy: (busy: boolean) => void;
  setErrors: (errors: FieldErrors) => void;
  setNotice: (notice: string) => void;
  setDetail: (detail: ConnectionDetail) => void;
  setDraftState: (draft: ConnectionDraft) => void;
  setTestResult: (result: TestResult | null) => void;
};

// Sends only what changed; a refusal is shown at its field (or as the notice) and returned as words.
export async function sendConnectionChanges(deps: ConnectionDetailDeps): Promise<string> {
  const { id, changes, binding, types, setBusy, setErrors, setNotice } = deps;
  setBusy(true);
  setErrors(null);
  const result = await updateConnection(id, changes);
  setBusy(false);
  if (!result.ok) {
    const message = result.field === "bound_scopes" ? boundScopesErrorText(result.message, binding) : result.message;
    setErrors({ field: result.field, message });
    setNotice(result.field ? "" : message);
    return message;
  }
  setNotice("Changes saved.");
  if (result.detail) {
    deps.setDetail(result.detail);
    deps.setDraftState(draftOf(result.detail, scopeKeyOf(result.detail.type, types)));
  } else await deps.load();
  deps.onChanged();
  return "";
}

// Binding the first keys of an unbound connection changes what other runs read: it is confirmed in the page first.
export async function saveConnection(deps: ConnectionDetailDeps): Promise<void> {
  const { detail, changes, binding, dirty, keysProblem, unboundToday, confirm } = deps;
  if (!dirty || keysProblem || !detail) return;
  const bound = Array.isArray(changes.bound_scopes) ? changes.bound_scopes as string[] : null;
  const first = Boolean(binding && bound && bindsFirstKeys(detail.boundScopes, bound));
  if (!binding || !bound || (!first && !unbindsAll(detail.boundScopes, bound))) {
    await sendConnectionChanges(deps);
    return;
  }
  const lines = first ? firstBindingText(binding, bound, keysLeftOut(unboundToday, bound)) : unbindText(binding, detail.boundScopes);
  confirm.ask({
    title: first ? `Bind ${detail.name} to ${bound.join(", ")}?` : `Unbind ${detail.name} from ${detail.boundScopes.join(", ")}?`,
    body: <>{lines.map((line) => <p key={line}>{line}</p>)}</>,
    confirmLabel: first ? "Bind and save" : "Unbind and save",
    run: async () => {
      const refused = await sendConnectionChanges(deps);
      if (refused) throw new Error(refused);
    },
    done: first ? `${detail.name} now serves ${bound.join(", ")}.` : `${detail.name} is no longer bound.`,
  });
}

export async function runConnectionTest(deps: ConnectionDetailDeps): Promise<void> {
  const { id, setBusy, setTestResult, setNotice } = deps;
  setBusy(true);
  const result = await testConnection(id);
  setBusy(false);
  setTestResult(result);
  setNotice(result ? "" : "The test could not be run.");
  if (result) {
    deps.onChanged();
    // The header's "tested …" follows the test (fresh-install test: it said "not tested yet" beside a
    // working result); only the stored facts are read again, an unsaved edit in the form stays.
    const next = await loadConnection(id).catch(() => null);
    if (next) deps.setDetail(next);
  }
}

export function askDeleteConnection(deps: ConnectionDetailDeps): void {
  const { detail, confirm } = deps;
  if (!detail) return;
  confirm.ask({
    title: `Delete connection ${detail.name}?`,
    body: <p>It can be deleted only while nothing uses it. This cannot be undone.</p>,
    confirmLabel: `Delete ${detail.name}`,
    tone: "danger",
    run: async () => {
      const result = await deleteConnection(detail.id);
      if (!result.ok) throw new Error(result.text);
      deps.onChanged();
      deps.onDeleted?.();
    },
    done: `Connection ${detail.name} deleted.`,
  });
}

// Resetting a Workspace's deviation reloads the connection and tells the list.
export async function resetConnectionDeviation(deps: ConnectionDetailDeps, workspaceId: string, connectionId: string): Promise<boolean> {
  const ok = await resetDeviation(workspaceId, connectionId);
  if (ok) {
    await deps.load();
    deps.onChanged();
  }
  return ok;
}
