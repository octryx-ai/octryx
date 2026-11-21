// The state of a Workspace's connector connection: what the server holds, the chosen mode, the sign-in draft, busy and
// message, the focus after a rebind refusal and the confirmation before switching back to global. Loading follows the
// Workspace and connector (and Retry); the ready flag and the rebind focus follow the state.
import { useCallback, useEffect, useState } from "react";

import { connectorFieldInputId } from "../../secretRebind/useConnectorSecretRebind";
import type { AtlassianProduct } from "../connectorsTab/atlassianAuthModes";
import { CONNECTION_UNREADABLE, connectionLoadFailure } from "./workspaceConnectionMessages";
import { connectionDraft, connectionUrl, ownConnectionReady, parseConnection } from "./workspaceConnectionModel";
import type { ConnectionMode, WorkspaceConnection } from "./workspaceConnectionTypes";

type ReadJson = <T = unknown>(url: string, init?: RequestInit) => Promise<T>;
export type LoadState = "loading" | "ready" | "error";

export function useWorkspaceConnectionState() {
  const [connection, setConnection] = useState<WorkspaceConnection | null>(
    null,
  );
  const [state, setState] = useState<LoadState>("loading");
  const [choice, setChoice] = useState<ConnectionMode>("global");
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [attempted, setAttempted] = useState(false);
  const [busy, setBusy] = useState<"save" | "test" | "global" | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(
    null,
  );
  const [loadError, setLoadError] = useState<string | null>(null);
  // After a secret_rebind_required refusal, the secret field to re-enter gets the focus.
  const [focusField, setFocusField] = useState<string | null>(null);
  // Choosing "global" over a stored own connection asks first; the radio keeps "own" until confirmed.
  const [confirmingGlobal, setConfirmingGlobal] = useState(false);
  const [reload, setReload] = useState(0);

  const apply = useCallback((next: WorkspaceConnection) => {
    setConnection(next);
    setChoice(next.mode);
    setDraft(connectionDraft(next));
    setAttempted(false);
  }, []);

  return {
    connection, setConnection, state, setState, choice, setChoice, draft, setDraft, attempted, setAttempted, busy, setBusy,
    message, setMessage, loadError, setLoadError, focusField, setFocusField, confirmingGlobal, setConfirmingGlobal, reload, setReload,
    apply,
  };
}

export type ConnectionState = ReturnType<typeof useWorkspaceConnectionState>;

// Reads the connection; a failure or an answer that is not a connection is an error with its reason.
function loadConnection(url: string, readJson: ReadJson, apply: (next: WorkspaceConnection) => void,
  setState: (state: LoadState) => void, setLoadError: (text: string | null) => void) {
  let current = true;
  setState("loading");
  readJson(url)
    .then((payload) => {
      if (!current) return;
      const parsed = parseConnection(payload);
      if (!parsed) {
        setLoadError(CONNECTION_UNREADABLE);
        setState("error");
        return;
      }
      apply(parsed);
      setState("ready");
    })
    .catch((error: unknown) => {
      if (!current) return;
      setLoadError(connectionLoadFailure(error));
      setState("error");
    });
  return () => {
    current = false;
  };
}

export function useWorkspaceConnectionSync(s: ConnectionState, { projectId, connectorName, product, readJson, onReadyChange }: {
  projectId: string;
  connectorName: string;
  product: AtlassianProduct;
  readJson: ReadJson;
  onReadyChange?: (ready: boolean) => void;
}) {
  const { apply, setState, setLoadError, connection, focusField, setFocusField, reload } = s;
  useEffect(() => {
    return loadConnection(connectionUrl(projectId, connectorName), readJson, apply, setState, setLoadError);
  }, [projectId, connectorName, readJson, apply, reload, setState, setLoadError]);

  useEffect(() => {
    onReadyChange?.(ownConnectionReady(product, connection));
  }, [connection, product, onReadyChange]);

  useEffect(() => {
    if (!focusField || typeof document === "undefined") return;
    document
      .getElementById(connectorFieldInputId(connectorName, focusField))
      ?.focus();
    setFocusField(null);
  }, [focusField, connectorName, setFocusField]);
}
