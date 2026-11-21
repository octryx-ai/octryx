import { useCallback, useEffect, useState } from "react";

import { formatRelativeTime } from "../../utils/formatters";
import { AutomationIcon } from "../automation/AutomationIcon";
import { AdminHeaderActions } from "../AdminHeaderSlot";
import { DataTable, type DataTableColumn } from "../../../layout/DataTable";
import { ActionMenu } from "../workflowSurfaces/ActionMenu";
import { StatusLabel } from "../../../layout/StatusLabel";
import "../adminDetailFacts.css";
import "../automation/automationPages.css";
import { InboundEventRows } from "./InboundEventRows";
import { InboundWebhookCreateDrawer } from "./InboundWebhookCreateDrawer";
import { InboundWebhookDetailDrawer } from "./InboundWebhookDetailDrawer";
import {
  stateLine,
  weekLine,
  type ActionOption,
  type InboundEvent,
  type InboundSource,
  type InboundWebhook,
} from "./inboundWebhookModel";

const STATE_LABELS: Record<InboundWebhook["state"], string> = {
  active: "Active",
  needs_setup: "Needs setup",
  paused: "Paused",
};

// The table's columns; each renders from its webhook only.
const COLUMNS: DataTableColumn<InboundWebhook>[] = [
  {
    key: "name",
    header: "Name",
    grow: true,
    minWidth: "12rem",
    render: (webhook) => (
      <span className="admin-detail-name">
        <AutomationIcon kind={webhook.source_type} small />
        <span>{webhook.name}</span>
      </span>
    ),
  },
  { key: "source", header: "Source", nowrap: true, render: (webhook) => webhook.source_label },
  { key: "workspace", header: "Workspace", nowrap: true, clip: "10rem", render: (webhook) => <span title={webhook.workspace_name}>{webhook.workspace_name}</span> },
  {
    // Cut with "…" so Last alert stays inside the page at 1280; the full line is the tooltip.
    key: "starts",
    header: "Starts",
    nowrap: true,
    clip: "16rem",
    render: (webhook) => {
      const line = `${webhook.action?.name ?? "Nothing yet"} → ${webhook.result_to.label}`;
      return <span title={line}>{line}</span>;
    },
  },
  {
    key: "state",
    header: "State",
    nowrap: true,
    render: (webhook) => {
      const state = stateLine(webhook);
      return (
        <StatusLabel
          label={STATE_LABELS[webhook.state] ?? state.text}
          tone={webhook.state === "needs_setup" ? "attention" : "neutral"}
          title={state.text}
          testId={`inbound-state-${webhook.id}`}
        />
      );
    },
  },
  {
    key: "last",
    header: "Last alert",
    nowrap: true,
    render: (webhook) => (
      <span title={weekLine(webhook)}>
        {webhook.last_event ? formatRelativeTime(webhook.last_event.received_at) : "None yet"}
      </span>
    ),
  },
];

type ReadJson = <T>(input: string, init?: RequestInit) => Promise<T>;

type Props = {
  projects: { id: string; name: string }[];
  readJson: ReadJson;
};

function useInboundWebhooks(readJson: ReadJson) {
  const [webhooks, setWebhooks] = useState<InboundWebhook[]>([]);
  const [sources, setSources] = useState<InboundSource[]>([]);
  const [actions, setActions] = useState<ActionOption[]>([]);
  const [latest, setLatest] = useState<InboundEvent[]>([]);
  const [openId, setOpenId] = useState<string | null>(null);
  // Remove… from a row's ⋯ menu opens the webhook's panel with the confirmation asked.
  const [removing, setRemoving] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [hooks, catalog, tasks, events] = await Promise.all([
        readJson<InboundWebhook[]>("/admin/chat/api/panel/webhooks"),
        readJson<{ sources: InboundSource[] }>(
          "/admin/chat/api/panel/webhooks/catalog",
        ),
        readJson<ActionOption[]>("/admin/chat/api/panel/tasks"),
        readJson<InboundEvent[]>(
          "/admin/chat/api/panel/webhook-events?limit=10",
        ),
      ]);
      setWebhooks(hooks);
      setSources(catalog.sources);
      setActions(tasks);
      setLatest(events);
      setLoadError(null);
    } catch (err) {
      setLoadError(
        err instanceof Error ? err.message : "Webhooks could not be loaded.",
      );
    }
  }, [readJson]);

  useEffect(() => {
    void load();
  }, [load]);

  const toggle = async (webhook: InboundWebhook) => {
    try {
      const next = await readJson<InboundWebhook>(`/admin/chat/api/panel/webhooks/${webhook.id}`, {
        method: "PUT",
        body: JSON.stringify({ is_active: !webhook.is_active }),
      });
      setWebhooks((current) => current.map((item) => (item.id === next.id ? next : item)));
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Not saved.");
    }
  };
  return {
    webhooks, setWebhooks, sources, actions, latest, openId, setOpenId, removing, setRemoving, creating, setCreating,
    loadError, load, toggle,
  };
}

type InboundState = ReturnType<typeof useInboundWebhooks>;

// Webhooks → Inbound: alert arrives → signature checked → the chosen action starts in its Workspace →
// result delivered. One table row per webhook, the latest alerts of all webhooks below; the flow itself is in the page
// help (help/admin/webhooks.md).
export function InboundWebhooksPage({ projects, readJson }: Props) {
  const state = useInboundWebhooks(readJson);
  const { webhooks, latest, openId, setOpenId, setRemoving, setCreating, loadError, toggle } = state;

  return (
    <div className="automation-page">
      {/* How an alert flows (signature, grouping, the action, the result) is in the page help (help/admin/webhooks.md). */}
      <AdminHeaderActions>
        <button
          type="button"
          className="admin-panel__action-btn admin-panel__action-btn--primary"
          onClick={() => setCreating(true)}
          data-testid="inbound-webhook-new"
        >
          New webhook
        </button>
      </AdminHeaderActions>
      {loadError ? <div className="admin-panel__error">{loadError}</div> : null}
      {/* The webhooks as one compact table; a row opens its detail drawer (side panel). */}
      {loadError && webhooks.length === 0 ? null : (
        <DataTable<InboundWebhook>
          label="Inbound webhooks"
          testId="inbound-grid"
          rows={webhooks}
          rowKey={(webhook) => webhook.id}
          onOpen={(webhook) => { setRemoving(null); setOpenId(webhook.id); }}
          selectedKey={openId}
          rowMenu={(webhook) => (
            <ActionMenu
              row={{ objectName: webhook.name }}
              items={[
                { label: webhook.is_active ? "Pause" : "Resume", onSelect: () => void toggle(webhook) },
                { label: "Remove…", danger: true, onSelect: () => { setRemoving(webhook.id); setOpenId(webhook.id); } },
              ]}
            />
          )}
          empty={{
            text: "No inbound webhooks yet.",
            action: { label: "New webhook", onClick: () => setCreating(true) },
            testId: "inbound-webhooks-empty",
          }}
          columns={COLUMNS}
        />
      )}
      <div className="admin-panel__section-header">
        <span>Latest alerts, all webhooks</span>
      </div>
      <InboundEventRows events={latest} showWebhook />

      <InboundDrawers state={state} projects={projects} readJson={readJson} />
    </div>
  );
}

function InboundDrawers({ state, projects, readJson }: Props & { state: InboundState }) {
  const { webhooks, setWebhooks, sources, actions, openId, setOpenId, removing, setRemoving, creating, setCreating, load } = state;
  const open = webhooks.find((webhook) => webhook.id === openId) ?? null;
  return (
    <>
    {creating ? (
      <InboundWebhookCreateDrawer
        sources={sources}
        projects={projects}
        actions={actions}
        readJson={readJson}
        onCreated={(webhook) =>
          setWebhooks((current) => [...current, webhook])
        }
        onOpen={(id) => {
          setCreating(false);
          setOpenId(id);
          void load();
        }}
        onClose={() => {
          setCreating(false);
          void load();
        }}
      />
    ) : null}
    {open ? (
      <InboundWebhookDetailDrawer
        key={`${open.id}:${removing === open.id ? "remove" : "view"}`}
        webhook={open}
        initialConfirm={removing === open.id ? "remove" : null}
        source={sources.find((source) => source.key === open.source_type)}
        actions={actions}
        readJson={readJson}
        onChanged={(next) => {
          if (!next) {
            setOpenId(null);
            void load();
            return;
          }
          setWebhooks((current) =>
            current.map((webhook) =>
              webhook.id === next.id ? next : webhook,
            ),
          );
        }}
        onClose={() => {
          setOpenId(null);
          setRemoving(null);
          void load();
        }}
      />
    ) : null}
    </>
  );
}
