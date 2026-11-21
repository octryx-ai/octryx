// The inbound webhook side panel's server actions (save, test alert, rotate, remove) as plain functions over the
// panel's state setters. Pure of React: the panel creates them on every render.
import type { Dispatch, SetStateAction } from "react";

import type { InboundEvent, InboundWebhook } from "./inboundWebhookModel";

type ReadJson = <T>(input: string, init?: RequestInit) => Promise<T>;

export type InboundTestResult = { tone: "ok" | "warn"; text: string };
export type InboundConfirm = "rotate" | "remove" | null;

export type DetailActionDeps = {
  base: string;
  webhook: InboundWebhook;
  sample: string;
  readJson: ReadJson;
  onChanged: (webhook: InboundWebhook | null) => void;
  setEvents: Dispatch<SetStateAction<InboundEvent[]>>;
  setTestResult: Dispatch<SetStateAction<InboundTestResult | null>>;
  setError: Dispatch<SetStateAction<string | null>>;
  setBusy: Dispatch<SetStateAction<boolean>>;
  setRotated: Dispatch<SetStateAction<InboundWebhook | null>>;
  setConfirm: Dispatch<SetStateAction<InboundConfirm>>;
};

function signatureWords(method: string | null | undefined): string {
  return method ? "signature valid" : "signature not checked";
}

function testResultFor(
  result: { outcome: string; message: string; signature?: string | null },
  webhook: InboundWebhook,
): InboundTestResult {
  return result.outcome === "started"
    ? {
        tone: "ok",
        text: `Accepted · ${signatureWords(result.signature)} · analysis started in ${webhook.workspace_name} (test run, nothing is posted).`,
      }
    : {
        tone: "warn",
        text: `Accepted · ${signatureWords(result.signature)} · ${result.message}`,
      };
}

export function createDetailActions(deps: DetailActionDeps) {
  const { base, readJson, onChanged, setEvents, setBusy, setError } = deps;
  const loadEvents = async () => {
    try {
      setEvents(await readJson<InboundEvent[]>(`${base}/events?limit=20`));
    } catch {
      setEvents([]);
    }
  };

  const run = async (work: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await work();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Not saved.");
    } finally {
      setBusy(false);
    }
  };

  const save = (patch: Record<string, unknown>) =>
    run(async () => {
      onChanged(
        await readJson<InboundWebhook>(base, {
          method: "PUT",
          body: JSON.stringify(patch),
        }),
      );
    });

  const sendTest = () =>
    run(async () => {
      const result = await readJson<{
        outcome: string;
        message: string;
        signature?: string | null;
      }>(`${base}/test`, {
        method: "POST",
        body: JSON.stringify({ sample: deps.sample }),
      });
      deps.setTestResult(testResultFor(result, deps.webhook));
      await loadEvents();
    });

  return { loadEvents, save, sendTest, ...secretActions(deps, run) };
}

function secretActions(deps: DetailActionDeps, run: (work: () => Promise<void>) => Promise<void>) {
  const { base, readJson, onChanged, setConfirm } = deps;
  const rotate = () =>
    run(async () => {
      const next = await readJson<InboundWebhook>(`${base}/rotate-secret`, {
        method: "POST",
      });
      deps.setRotated(next);
      setConfirm(null);
    });

  const remove = () =>
    run(async () => {
      await readJson(base, { method: "DELETE" });
      setConfirm(null);
      onChanged(null);
    });
  return { rotate, remove };
}
