import { useCallback, useEffect, useState } from "react";
import { connectorsApi } from "./connectorsApi";
import type { SourceConnector, SyncRun } from "./connectorTypes";
import { useConfirmAction } from "../confirm/useConfirmAction";
import { useAdminNavigation } from "../../adminNavigation";
import { ADD_SOURCE_KEY } from "./sourceLinks";

export function errorText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** The source a link asks for (?source=<key>), and whether as a page (&source_view=page). */
function requestedSource(): { key: string; page: boolean } | null {
  try {
    const params = new URLSearchParams(typeof window === "undefined" ? "" : window.location?.search ?? "");
    const key = params.get("source");
    return key ? { key, page: params.get("source_view") === "page" } : null;
  } catch {
    return null;
  }
}

// The form, run and refusal state of the sources panel.
function useConnectorFormState() {
  const [editing, setEditing] = useState<SourceConnector | null>(null);
  // The form for a new source opens only on "Add source", or from a link that asks for it
  // (?source=new, sourceLinks.ts); editing opens it for that connector.
  const [adding, setAdding] = useState(() => requestedSource()?.key === ADD_SOURCE_KEY);
  // The Jira connector whose releases block is open in the drawer.
  const [releasesKey, setReleasesKey] = useState<string | null>(null);
  const [runningKey, setRunningKey] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  // Fail closed: a listing that does not report the role shows no authoring controls.
  const [mayAuthor, setMayAuthor] = useState(false);
  // The listing as returned, so the instance scheduler switch is read from it when the server reports it.
  const [listing, setListing] = useState<unknown>(null);
  // A refused save that belongs to the connector's scope, shown in the form next to the scope fields.
  const [scopeRefusal, setScopeRefusal] = useState<string | null>(null);
  // The last refused save itself: a REST source shows it at the field it names.
  const [saveRefusal, setSaveRefusal] = useState<unknown>(null);
  // "From a connection" has its own save; then the panel shows no footer of its own.
  const [formOwnActions, setFormOwnActions] = useState(false);
  // "Open as page" (?source=<key>&source_view=page) shows that source alone.
  const [pageView] = useState(() => requestedSource()?.page === true);
  return {
    editing, setEditing, adding, setAdding, releasesKey, setReleasesKey, runningKey, setRunningKey, busy, setBusy,
    message, setMessage, mayAuthor, setMayAuthor, listing, setListing, scopeRefusal, setScopeRefusal,
    saveRefusal, setSaveRefusal, formOwnActions, setFormOwnActions, pageView,
  };
}

export function useKnowledgeConnectorsState(workspaceId: string) {
  const [connectors, setConnectors] = useState<SourceConnector[] | null>(null);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [lastRun, setLastRun] = useState<SyncRun | null>(null);
  const confirmAction = useConfirmAction();
  const form = useConnectorFormState();
  const { setMessage, setListing, setMayAuthor } = form;
  const { openAdminTab } = useAdminNavigation();

  const showRun = useCallback(async (connectorKey: string) => {
    setSelectedKey(connectorKey);
    try {
      setLastRun((await connectorsApi.lastRun(workspaceId, connectorKey)).run);
    } catch (err) {
      setLastRun(null);
      setMessage(errorText(err));
    }
  }, [workspaceId, setMessage]);

  const refresh = useCallback(async () => {
    const response = await connectorsApi.list(workspaceId);
    setListing(response);
    setConnectors(response.connectors);
    setMayAuthor(response.may_author === true);
    return response.connectors;
  }, [workspaceId, setListing, setMayAuthor]);

  // A source opens on demand (design system); only a link with ?source=<key> opens one right away.
  useEffect(() => {
    refresh()
      .then((listed) => {
        const wanted = requestedSource()?.key;
        return wanted && listed.some((item) => item.connector_key === wanted) ? showRun(wanted) : undefined;
      })
      .catch((err: unknown) => setMessage(errorText(err)));
  }, [refresh, showRun, setMessage]);

  return { connectors, selectedKey, setSelectedKey, lastRun, setLastRun, confirmAction, ...form, openAdminTab, showRun, refresh };
}

export type KnowledgeConnectorsState = ReturnType<typeof useKnowledgeConnectorsState>;
