import { useCallback, useEffect, useState } from "react";

import { proposalsLoadProblem, readProposals, withDecided, type ProposalsPayload, type RuleProposal } from "./prReviewBotRulesModel";
import { call, workspacePath } from "./reviewBotApi";

export type RuleProposalsState = {
  payload: ProposalsPayload | null;
  problem: string | null;
  reload: () => void;
  replace: (row: RuleProposal) => void;
};

export const proposalsPath = (workspaceId: string) => `${workspacePath(workspaceId)}/pr-review-bot/rule-proposals`;
export const day = (iso: string) => {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
};

/** One read for the whole Workspace; every repository card filters its own rows. */
export function useRuleProposals(workspaceId: string): RuleProposalsState {
  const [payload, setPayload] = useState<ProposalsPayload | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [round, setRound] = useState(0);

  useEffect(() => {
    let current = true;
    setProblem(null);
    void call(proposalsPath(workspaceId)).then((answer) => {
      if (!current) return;
      if (answer.ok) { setPayload(readProposals(answer.body)); return; }
      setPayload(null);
      setProblem(proposalsLoadProblem(answer.status, answer.body));
    });
    return () => { current = false; };
  }, [workspaceId, round]);

  const reload = useCallback(() => setRound((value) => value + 1), []);
  const replace = useCallback((row: RuleProposal) => setPayload((current) => current && ({
    ...current, proposals: withDecided(current.proposals, row),
  })), []);
  return { payload, problem, reload, replace };
}

