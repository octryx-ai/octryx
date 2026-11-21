// Save, Test and Use global of a Workspace connector connection, with the secret rebind refusal handling.
import type { AtlassianAuthView } from "../connectorsTab/atlassianAuthView";
import type { AtlassianProduct } from "../connectorsTab/atlassianAuthModes";
import { authModeFields } from "../connectorsTab/atlassianAuthModes";
import { connectionUrl, parseConnection, sourceOf } from "./workspaceConnectionModel";
import { settledMessage, testResultText } from "./workspaceConnectionMessages";
import { rebindFocusField, rebindRefusalOf, rebindRefusalText } from "./workspaceConnectionRebind";
import { type WorkspaceConnection } from "./workspaceConnectionTypes";

type ReadJson = <T = unknown>(url: string, init?: RequestInit) => Promise<T>;
type Message = { ok: boolean; text: string } | null;

type Input = {
  projectId: string;
  connectorName: string;
  product: AtlassianProduct;
  label: string;
  readJson: ReadJson;
  view: AtlassianAuthView;
  hasErrors: boolean;
  ownBody: () => Record<string, unknown>;
  apply: (next: WorkspaceConnection) => void;
  setBusy: (busy: "save" | "test" | "global" | null) => void;
  setMessage: (message: Message) => void;
  setFocusField: (field: string | null) => void;
  setAttempted: (attempted: boolean) => void;
  setConnection: (update: (current: WorkspaceConnection | null) => WorkspaceConnection | null) => void;
  setConfirmingGlobal: (confirming: boolean) => void;
};

// Runs one request with the busy state and the refusal message, and settles a saved connection from the server.
function workspaceConnectionRunner({ projectId, connectorName, product, label, readJson, view, apply, setBusy, setMessage,
  setFocusField }: Input) {
  const run = async (
    kind: "save" | "test" | "global",
    action: () => Promise<void>,
  ) => {
    setBusy(kind);
    setMessage(null);
    try {
      await action();
    } catch (error) {
      // A changed URL with a kept secret is refused (409). Never retried: the author re-enters it.
      const refusal = rebindRefusalOf(error);
      if (refusal && kind !== "global") {
        const chosen = view.mode ? authModeFields(product, view.mode) : null;
        const focus = rebindFocusField(refusal, chosen?.secret ?? null);
        const secretLabel =
          chosen && focus === chosen.secret
            ? chosen.secretLabel
            : (focus ?? "secret").replace(/_/g, " ");
        setMessage({
          ok: false,
          text: rebindRefusalText(kind, label, secretLabel),
        });
        setFocusField(focus);
        return;
      }
      setMessage({
        ok: false,
        text: error instanceof Error ? error.message : "The request failed.",
      });
    } finally {
      setBusy(null);
    }
  };
  // The shown connection always comes from the server. An unreadable PUT answer is followed by
  // a fresh read; success is claimed only when the server then reports the expected mode.
  const settle = async (
    answer: unknown,
  ): Promise<WorkspaceConnection | null> => {
    const parsed =
      parseConnection(answer) ??
      parseConnection(
        await readJson(connectionUrl(projectId, connectorName)).catch(
          () => null,
        ),
      );
    if (parsed) apply(parsed);
    return parsed;
  };
  return { run, settle };
}

export function workspaceConnectionActions(input: Input) {
  const { projectId, connectorName, label, readJson, hasErrors, ownBody, setMessage, setAttempted, setConnection,
    setConfirmingGlobal } = input;
  const { run, settle } = workspaceConnectionRunner(input);
  const save = () => {
    if (hasErrors) {
      setAttempted(true);
      return;
    }
    void run("save", async () => {
      const saved = await settle(
        await readJson(connectionUrl(projectId, connectorName), {
          method: "PUT",
          body: JSON.stringify(ownBody()),
        }),
      );
      setMessage(
        settledMessage(
          saved,
          "own",
          `Saved this Workspace's own ${label} connection.`,
        ),
      );
    });
  };
  const test = () => {
    if (hasErrors) {
      setAttempted(true);
      return;
    }
    void run("test", async () => {
      const result = await readJson(
        connectionUrl(projectId, connectorName, "/test"),
        { method: "POST", body: JSON.stringify(ownBody()) },
      );
      setMessage(testResultText(result));
      // A test of the saved connection is recorded as its health: refresh only that, keep the typed draft.
      const latest = parseConnection(
        await readJson(connectionUrl(projectId, connectorName)).catch(
          () => null,
        ),
      );
      if (latest)
        setConnection((current) =>
          current ? { ...current, health: latest.health } : current,
        );
    });
  };
  const useGlobal = () =>
    void run("global", async () => {
      const saved = await settle(
        await readJson(connectionUrl(projectId, connectorName), {
          method: "PUT",
          body: JSON.stringify({ source: sourceOf("global") }),
        }),
      );
      setConfirmingGlobal(false);
      setMessage(
        settledMessage(
          saved,
          "global",
          `This Workspace now uses the global ${label} connection.`,
        ),
      );
    });
  return { save, test, useGlobal };
}
