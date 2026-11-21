import { useEffect, useState } from "react";

import { ToggleRow } from "../../settingsKit/SettingsKit";
import { REVIEW_SEAT_SUB, REVIEW_SEAT_TITLE } from "./prReviewBotLimits";
import { call, workspacePath } from "./reviewBotApi";

// PR review bot › the viewer's own review seat in this Workspace (GET/PUT …/pr-review-bot/review-seat, any member for
// themself). Hidden when the server has no such route.
export function ReviewSeatToggle({ workspaceId }: { workspaceId: string }) {
  const [on, setOn] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const path = `${workspacePath(workspaceId)}/pr-review-bot/review-seat`;

  useEffect(() => {
    let current = true;
    setOn(null); setProblem(null);
    void call(path).then((answer) => {
      if (!current) return;
      const enabled = (answer.body as { enabled?: unknown } | null)?.enabled;
      if (answer.ok && typeof enabled === "boolean") setOn(enabled);
    });
    return () => { current = false; };
  }, [path]);

  if (on === null) return null;
  const change = async (next: boolean) => {
    setBusy(true); setProblem(null);
    const answer = await call(path, "PUT", { enabled: next });
    setBusy(false);
    const enabled = (answer.body as { enabled?: unknown } | null)?.enabled;
    if (answer.ok) setOn(typeof enabled === "boolean" ? enabled : next);
    else setProblem(answer.status === 0 ? "Not saved: the request did not reach the server." : "Not saved. Try again.");
  };
  return (
    <div className="review-bot__seat" data-testid="review-bot-seat">
      <ToggleRow title={REVIEW_SEAT_TITLE} sub={REVIEW_SEAT_SUB} on={on} disabled={busy}
        onChange={(next) => void change(next)} testId="review-bot-seat-toggle" />
      {problem ? <p className="sk-err" role="alert">{problem}</p> : null}
    </div>
  );
}
