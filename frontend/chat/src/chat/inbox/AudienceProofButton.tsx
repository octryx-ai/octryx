import { useState } from "react";
import { readJson } from "../chatApiClient";

export function AudienceProofButton({ challengeId }: { challengeId: string }) {
  const [state, setState] = useState<"idle" | "running" | "recorded" | "failed">("idle");
  async function record() {
    if (state === "running" || state === "recorded") return;
    setState("running");
    try {
      await readJson(`/api/v1/workflow-runs/audience-receipts/${encodeURIComponent(challengeId)}/record`,
        { method: "POST" });
      setState("recorded");
    } catch {
      setState("failed");
    }
  }
  return <span>
    <button type="button" className="admin-panel__action-btn" onClick={() => void record()}
      disabled={state === "running" || state === "recorded"}>
      {state === "running" ? "Checking…" : state === "recorded" ? "Recorded" : "Run access check"}
    </button>
    {state === "failed" ? <span role="status">The check could not be recorded. Sign in as the assigned user or retry.</span> : null}
  </span>;
}
