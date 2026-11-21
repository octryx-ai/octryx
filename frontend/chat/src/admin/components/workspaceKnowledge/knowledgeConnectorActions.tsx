import { configOf } from "./connectorConfig";
import { connectorsApi } from "./connectorsApi";
import { reasonText } from "./connectorReasons";
import type { ConnectorConfig, SourceConnector } from "./connectorTypes";
import { sourceName } from "./sources/sourceState";
import { runResultText } from "./connectorFreshness";
import { scopeRefusalText } from "./connectorScopeText";
import { REST_KIND } from "./rest/restSourceForm";
import { restRefusalOf } from "./rest/restSourceRefusals";
import { errorText, type KnowledgeConnectorsState } from "./useKnowledgeConnectorsState";

type Act = (action: () => Promise<string | null>) => Promise<boolean>;

function makeAct(s: KnowledgeConnectorsState): Act {
  return async (action) => {
    s.setBusy(true);
    try {
      s.setMessage(await action());
      return true;
    } catch (err) {
      s.setMessage(errorText(err));
      return false;
    } finally {
      s.setBusy(false);
    }
  };
}

function makeSave(s: KnowledgeConnectorsState, workspaceId: string, act: Act) {
  return (connectorKey: string, config: ConnectorConfig) =>
    act(async () => {
      s.setScopeRefusal(null);
      s.setSaveRefusal(null);
      try {
        await connectorsApi.configure(workspaceId, connectorKey, config);
      } catch (err) {
        // A scope refusal (page-tree shape, or a space outside the allowlist) is also shown next to the scope.
        s.setScopeRefusal(scopeRefusalText(err));
        s.setSaveRefusal(err);
        // A REST source's refusal in words, never the field's technical name.
        if (config.kind === REST_KIND) throw new Error(`Not saved: ${restRefusalOf(err).text}`);
        throw err;
      }
      s.setEditing(null);
      s.setAdding(false);
      await s.refresh();
      await s.showRun(connectorKey);
      return config.state === "paused" ? `Saved ${connectorKey} (paused).` : `Saved ${connectorKey}. Run it now to sync.`;
    });
}

// Pause confirms in the page: its schedule stops until someone resumes it. Resume needs no confirm.
function makeToggle(s: KnowledgeConnectorsState, workspaceId: string, act: Act) {
  return (connector: SourceConnector) => {
    const key = connector.connector_key;
    const name = sourceName(connector);
    if (connector.state === "paused") {
      void act(async () => {
        await connectorsApi.configure(workspaceId, key, configOf(connector, "active"));
        await s.refresh();
        return `Resumed ${sourceName(connector)}.`;
      });
      return;
    }
    s.confirmAction.ask({
      title: `Pause source ${name}?`,
      body: <p>Its schedule stops until someone resumes it. Nothing it already synced is removed.</p>,
      confirmLabel: `Pause ${name}`, tone: "neutral",
      run: async () => {
        await connectorsApi.configure(workspaceId, key, configOf(connector, "paused"));
        s.setMessage(null);
        await s.refresh();
      },
      done: `Source ${name} paused.`,
    });
  };
}

function makeRemove(s: KnowledgeConnectorsState, workspaceId: string) {
  return (connector: SourceConnector) => {
    const key = connector.connector_key;
    const name = sourceName(connector);
    s.confirmAction.ask({
      title: `Remove source ${name}?`,
      body: <p>Its schedule stops and its configuration and run history are removed. What it already synced stays in this Workspace.</p>,
      confirmLabel: `Remove ${name}`,
      run: async () => {
        await connectorsApi.remove(workspaceId, key);
        if (s.editing?.connector_key === key) s.setEditing(null);
        if (s.releasesKey === key) s.setReleasesKey(null);
        if (s.selectedKey === key) {
          s.setSelectedKey(null);
          s.setLastRun(null);
        }
        s.setMessage(null);
        await s.refresh();
      },
      done: `Source ${name} removed. What it already synced stays in this Workspace.`,
    });
  };
}

function makeRunNow(s: KnowledgeConnectorsState, workspaceId: string, act: Act) {
  return (connector: SourceConnector) => {
    s.setRunningKey(connector.connector_key);
    s.setMessage(`Syncing ${sourceName(connector)}… a sync reads at most ${connector.max_items_per_run} items.`);
    void act(async () => {
      try {
        const run = await connectorsApi.run(workspaceId, connector.connector_key);
        await s.showRun(connector.connector_key);
        const result = runResultText(run, connector.kind);
        const reason = reasonText(run.reason);
        return reason ? `${result} ${reason.charAt(0).toUpperCase()}${reason.slice(1)}.` : result;
      } finally {
        s.setRunningKey(null);
        await s.refresh().catch(() => undefined);
      }
    });
  };
}

// The panel's actions, built on every render from that render's state (as the inline closures were).
export function knowledgeConnectorActions(s: KnowledgeConnectorsState, workspaceId: string) {
  const act = makeAct(s);
  // An open edit form of the same connector would send the old releases block back: it reopens on the saved one.
  const releasesSaved = async (connectorKey: string) => {
    const listed = await s.refresh().catch(() => null);
    if (listed) s.setEditing((current) => (current?.connector_key === connectorKey ? listed.find((item) => item.connector_key === connectorKey) ?? null : current));
  };
  return {
    closeDetail: () => {
      s.setSelectedKey(null);
      s.setLastRun(null);
    },
    save: makeSave(s, workspaceId, act),
    toggle: makeToggle(s, workspaceId, act),
    releasesSaved,
    remove: makeRemove(s, workspaceId),
    runNow: makeRunNow(s, workspaceId, act),
    closeForm: () => { s.setEditing(null); s.setAdding(false); s.setScopeRefusal(null); s.setSaveRefusal(null); },
    openAdd: () => { s.setEditing(null); s.setSelectedKey(null); s.setAdding(true); },
    edit: (connector: SourceConnector) => { s.setSelectedKey(null); s.setAdding(false); s.setEditing(connector); },
  };
}

export type KnowledgeConnectorActions = ReturnType<typeof knowledgeConnectorActions>;
