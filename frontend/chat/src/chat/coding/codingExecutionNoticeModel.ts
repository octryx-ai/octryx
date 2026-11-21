export type CodingExecutionNoticeData = {
  title: string;
  message: string;
  workUrl?: string;
  codingUrl?: string;
};

export function blockedExecutionMessage(result: {
  blockers: Array<Record<string, unknown>>;
  reason?: string;
  source_key: string;
}): string {
  const firstBlocker = result.blockers[0] || {};
  const code = typeof firstBlocker.code === "string" ? firstBlocker.code : "";
  if (code === "source_changed_after_plan") {
    return `${result.source_key} changed after the approved Work Plan. No chat session was created; generate a new Work Plan from the latest Jira evidence before starting the agent.`;
  }
  if (code) {
    return `${result.source_key} failed coding preflight with blocker ${code}. No chat session was created; review the Work Item and resolve the blocker before starting the agent.`;
  }
  return `${result.source_key} failed coding preflight${
    result.reason ? ` (${result.reason})` : ""
  }. No chat session was created; review the Work Item before starting the agent.`;
}
