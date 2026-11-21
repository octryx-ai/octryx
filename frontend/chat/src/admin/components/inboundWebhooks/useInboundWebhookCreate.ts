// The state of the inbound webhook create form and its one create request.
import { useEffect, useState } from "react";

import { useAdminNavigation } from "../../adminNavigation";
import {
  actionsForWorkspace,
  cannotSignTimestamp,
  timestampFixedReason,
  type ActionOption,
  type InboundSource,
  type InboundWebhook,
} from "./inboundWebhookModel";

export type ReadJson = <T>(input: string, init?: RequestInit) => Promise<T>;

export type ResultChannel = { id: number; name: string; project_id: string | null; enabled?: boolean };

type CreateFields = {
  name: string;
  projectId: string;
  source: string;
  taskId: string;
  polled: boolean;
  untimestamped: boolean;
  pollQuery: string;
  resultTo: string;
};

/** The create request body. */
export function inboundWebhookBody(form: CreateFields): string {
  const { name, projectId, source, taskId, polled, untimestamped, pollQuery, resultTo } = form;
  return JSON.stringify({
    name: name.trim(),
    project_id: projectId,
    source_type: source,
    task_id: taskId || null,
    accept_untimestamped: polled ? false : untimestamped || Boolean(timestampFixedReason(source)),
    ...(polled ? { poll_query: pollQuery.trim() } : {}),
    // "Send the result to" sets the action's own destination (one declaration); "keep" leaves it.
    ...(taskId && resultTo !== "keep"
      ? { result_channel_id: resultTo === "" ? null : Number(resultTo) }
      : {}),
  });
}

export function useInboundWebhookCreate({
  sources,
  actions,
  readJson,
  onCreated,
}: {
  sources: InboundSource[];
  actions: ActionOption[];
  readJson: ReadJson;
  onCreated: (webhook: InboundWebhook) => void;
}) {
  const [source, setSource] = useState(sources[0]?.key ?? "alertmanager");
  const [name, setName] = useState("");
  const [projectId, setProjectId] = useState("");
  const [taskId, setTaskId] = useState("");
  const [pollQuery, setPollQuery] = useState("");
  const [untimestamped, setUntimestamped] = useState(
    cannotSignTimestamp(source),
  );
  const [resultTo, setResultTo] = useState("keep");
  const [channels, setChannels] = useState<ResultChannel[]>([]);
  const { openAdminTab } = useAdminNavigation();
  useEffect(() => {
    readJson<typeof channels>("/admin/chat/api/panel/channels").then(
      setChannels,
      () => setChannels([]),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const polled = Boolean(
    sources.find((option) => option.key === source)?.polled,
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<InboundWebhook | null>(null);

  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      const body = inboundWebhookBody({ name, projectId, source, taskId, polled, untimestamped, pollQuery, resultTo });
      const webhook = await readJson<InboundWebhook>("/admin/chat/api/panel/webhooks", { method: "POST", body });
      setCreated(webhook);
      onCreated(webhook);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Not created.");
    } finally {
      setBusy(false);
    }
  };

  return {
    source, setSource, name, setName, projectId, setProjectId, taskId, setTaskId, pollQuery, setPollQuery,
    untimestamped, setUntimestamped, resultTo, setResultTo, openAdminTab, polled, busy, error, created, create,
    workspaceChannels: channels.filter((channel) => !channel.project_id || channel.project_id === projectId),
    workspaceActions: actionsForWorkspace(actions, projectId),
  };
}

export type InboundWebhookCreateState = ReturnType<typeof useInboundWebhookCreate>;
