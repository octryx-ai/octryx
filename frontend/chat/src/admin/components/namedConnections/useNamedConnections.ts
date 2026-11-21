import { useCallback, useEffect, useState } from "react";

import { atlassianAuthSaveFields } from "../connectorsTab/atlassianAuthModel";
import { atlassianAuthView } from "../connectorsTab/atlassianAuthView";
import { serviceNowAuthSaveFields, serviceNowAuthView } from "../connectorsTab/serviceNowAuthModel";
import type { AdminConnector } from "../../types/adminPanelTypes.usersProviders";
import type { Editing } from "./NamedConnectionEditor";
import { fieldsSaveFields, fieldsView } from "./namedFieldsModel";
import { boundElsewhere, nameProblem, namedAsConnector, namedDraft, parseScopes, scopesProblem } from "./namedConnectionsForm";
import { namedConnectionsUrl, parseNamedConnection, parseNamedConnections } from "./namedConnectionsParse";
import { refusalText } from "./namedConnectionsText";
import type { NamedConnection, NamedConnectionList } from "./namedConnectionsTypes";
import { rebindRefusalOf } from "../projectsTab/workspaceConnectionRebind";
import { testResultText } from "../projectsTab/workspaceConnectionMessages";
import { scopeCheckOf } from "../connectorTest/scopeCheckModel";
import type { ScopeCheck } from "../connectorTest/scopeCheckModel";

export type ReadJson = <T = unknown>(url: string, init?: RequestInit) => Promise<T>;
export type Message = { ok: boolean; text: string; scopeCheck?: ScopeCheck | null } | null;

// The list of one connector's named connections, its load state and the open form, message and delete step.
export function useNamedConnections(projectId: string | null, connector: string, readJson: ReadJson, onReadyChange?: (ready: boolean) => void) {
  const [list, setList] = useState<NamedConnectionList | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [editing, setEditing] = useState<Editing | null>(null);
  const [attempted, setAttempted] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<Message>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const parsed = parseNamedConnections(await readJson(namedConnectionsUrl(projectId, connector)));
      setList(parsed);
      setState(parsed ? "ready" : "error");
    } catch {
      setState("error");
    }
  }, [projectId, connector, readJson]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (projectId !== null && list) onReadyChange?.(list.connections.length > 0);
  }, [projectId, list, onReadyChange]);

  return { list, state, editing, setEditing, attempted, setAttempted, busy, setBusy, message, setMessage, confirmDelete, setConfirmDelete, load };
}

export type NamedConnectionsState = ReturnType<typeof useNamedConnections>;

// What the open form shows: the descriptor's form kind (Atlassian or ServiceNow sign-in, or its generic fields) and its problems.
export function namedFormView(connector: string, list: NamedConnectionList, editing: Editing | null) {
  const descriptor = list.descriptor;
  const asConnector = namedAsConnector(connector, editing?.connection ?? null) as unknown as AdminConnector;
  const draft = editing?.draft ?? {};
  const authView = descriptor.form === "atlassian_auth"
    ? atlassianAuthView(connector as "confluence" | "jira", asConnector, draft) : null;
  const snView = descriptor.form === "servicenow_auth" ? serviceNowAuthView(asConnector, draft) : null;
  const genericView = !authView && !snView ? fieldsView(descriptor, draft, editing?.connection ?? null) : null;
  const authErrors = Object.keys((authView ?? snView ?? genericView)?.errors ?? {}).length > 0;
  const ownId = editing?.connection?.id ?? null;
  const problems = editing
    ? [
        nameProblem(editing.name, list.connections, ownId),
        scopesProblem(descriptor, editing.scopes),
        ...boundElsewhere(descriptor, list.connections, ownId, editing.scopes).map(
          (clash) => `Already bound by another connection: ${clash}.`,
        ),
      ].filter((problem): problem is string => problem !== null)
    : [];
  return { descriptor, asConnector, draft, authView, snView, genericView, authErrors, ownId, problems };
}

type FormView = ReturnType<typeof namedFormView>;
type Ctx = { s: NamedConnectionsState; v: FormView; projectId: string | null; connector: string; label: string; readJson: ReadJson };

// The request body of a save or a test of the typed values.
function requestBody({ s, v, connector }: Ctx) {
  return {
    name: s.editing?.name.trim(),
    bound_scopes: parseScopes(v.descriptor, s.editing?.scopes ?? ""),
    ...(v.snView
      ? serviceNowAuthSaveFields(v.asConnector, v.draft)
      : v.authView
        ? atlassianAuthSaveFields(connector as "confluence" | "jira", v.asConnector, v.draft)
        : fieldsSaveFields(v.descriptor, v.draft)),
  };
}

function makeRun({ s, label }: Ctx) {
  return async (kind: string, action: () => Promise<void>) => {
    s.setBusy(kind);
    s.setMessage(null);
    try {
      await action();
    } catch (error) {
      const text = rebindRefusalOf(error)
        ? `The ${label} URL or client changed, so the stored secret is not sent there. Enter the secret again.`
        : refusalText(error);
      s.setMessage({ ok: false, text });
    } finally {
      s.setBusy(null);
    }
  };
}

function makeSave(ctx: Ctx, run: ReturnType<typeof makeRun>) {
  const { s, v, projectId, connector, label, readJson } = ctx;
  return () => {
    const editing = s.editing;
    if (!editing) return;
    if (v.problems.length || v.authErrors) {
      s.setAttempted(true);
      return;
    }
    void run("save", async () => {
      const saved = parseNamedConnection(
        await readJson(namedConnectionsUrl(projectId, connector, v.ownId ?? undefined), {
          method: v.ownId ? "PUT" : "POST",
          body: JSON.stringify(requestBody(ctx)),
        }),
      );
      await s.load();
      s.setEditing(null);
      const name = saved?.name ?? editing.name.trim();
      s.setMessage({ ok: true, text: `Saved the ${label} connection "${name}"${saved ? ` (${saved.id})` : ""}.` });
    });
  };
}

function openForm(s: NamedConnectionsState, connection: NamedConnection | null) {
  s.setEditing({
    connection,
    name: connection?.name ?? "",
    scopes: connection ? connection.boundScopes.join(", ") : "",
    draft: namedDraft(connection),
  });
  s.setAttempted(false);
  s.setMessage(null);
  s.setConfirmDelete(null);
}

// The panel's actions, built on every render from that render's state.
export function namedConnectionActions(ctx: Ctx) {
  const { s, projectId, connector, label, readJson } = ctx;
  const run = makeRun(ctx);
  const set = (field: string, value: string) => {
    s.setEditing((current) => (current ? { ...current, draft: { ...current.draft, [field]: value } } : current));
    s.setMessage(null);
  };
  const test = (connection: NamedConnection) =>
    void run(`test:${connection.id}`, async () => {
      const typed = s.editing?.connection?.id === connection.id ? requestBody(ctx) : {};
      const result = await readJson(namedConnectionsUrl(projectId, connector, connection.id, "/test"), {
        method: "POST",
        body: JSON.stringify(typed),
      });
      const outcome = testResultText(result);
      await s.load(); // the saved connection's test is kept as its last test
      s.setMessage({ ok: outcome.ok, text: `${connection.name}: ${outcome.text}`, scopeCheck: scopeCheckOf(result) });
    });
  const remove = (connection: NamedConnection) =>
    void run(`delete:${connection.id}`, async () => {
      await readJson(namedConnectionsUrl(projectId, connector, connection.id), { method: "DELETE" });
      s.setConfirmDelete(null);
      if (s.editing?.connection?.id === connection.id) s.setEditing(null);
      await s.load();
      s.setMessage({ ok: true, text: `Deleted the ${label} connection "${connection.name}".` });
    });
  return { set, open: (connection: NamedConnection | null) => openForm(s, connection), save: makeSave(ctx, run), test, remove };
}

export type NamedConnectionActions = ReturnType<typeof namedConnectionActions>;
