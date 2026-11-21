import { useEffect, useState } from "react";

import { BOT_INTRO } from "./prReviewBotTexts";
import { botLoadProblem, readBotPayload, type BotPayload, type BotRepository } from "./prReviewBotModel";
import { PrReviewBotCard } from "./PrReviewBotCard";
import { ReviewSeatToggle } from "./ReviewSeatToggle";
import { RuleProposalsBlock } from "./RuleProposals";
import { useRuleProposals } from "./useRuleProposals";
import { call, workspacePath } from "./reviewBotApi";
import "./prReviewBot.css";

// Workspace settings › Repositories › "PR review bot": one card per GitHub/GitLab/Bitbucket repository, all from one read.
export function PrReviewBotSection({ workspaceId }: { workspaceId: string }) {
  const [payload, setPayload] = useState<BotPayload | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const rules = useRuleProposals(workspaceId);

  useEffect(() => {
    let current = true;
    setPayload(null); setProblem(null); setUnavailable(false);
    void call(`${workspacePath(workspaceId)}/pr-review-bot`).then((answer) => {
      if (!current) return;
      if (answer.ok) { setPayload(readBotPayload(answer.body)); return; }
      const failure = botLoadProblem(answer.status, answer.body);
      if (failure.kind === "unavailable") setUnavailable(true);
      else setProblem(failure.text);
    });
    return () => { current = false; };
  }, [workspaceId]);

  // A server without the review bot (route missing) shows nothing.
  if (unavailable) return null;
  // The PUT's answer wins; the GET's webhook state stays only when the answer does not carry it.
  const replace = (row: BotRepository, webhookConfigured: boolean | null) => setPayload((current) => current && ({
    ...current,
    repositories: current.repositories.map((item) => (item.id === row.id ? row : item)),
    webhookConfigured: webhookConfigured ?? current.webhookConfigured,
  }));

  return (
    <section className="user-edit-panel__section review-bot" aria-label="PR review bot" data-testid="review-bot">
      <div className="user-edit-panel__section-label">PR review bot</div>
      <p className="sk-muted review-bot__intro">{BOT_INTRO}</p>
      <ReviewSeatToggle workspaceId={workspaceId} />
      {problem ? <p className="sk-err" role="alert">{problem}</p> : null}
      {!payload && !problem ? <div className="admin-panel__empty-state">Loading the review bot settings…</div> : null}
      {payload && !payload.repositories.length ? (
        <div className="admin-panel__empty-state" data-testid="review-bot-empty">
          No GitHub, GitLab or Bitbucket repository in this Workspace yet. The review bot works on those only.
        </div>
      ) : null}
      {payload?.repositories.map((row) => (
        <PrReviewBotCard key={row.id} workspaceId={workspaceId} row={row} triggers={payload.triggers}
          canEdit={payload.canEdit} webhookConfigured={payload.webhookConfigured} onSaved={replace}>
          <RuleProposalsBlock workspaceId={workspaceId} repositoryId={row.id} repositoryName={row.name} rules={rules} />
        </PrReviewBotCard>
      ))}
    </section>
  );
}
