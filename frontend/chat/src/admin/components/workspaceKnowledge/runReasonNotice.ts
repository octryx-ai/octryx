// A fixed Source Sync reason that is a policy refusal, not a source-system failure, gets an explicit notice with its
// code in the run report. `egress_refused`: the platform's outbound policy refused the connection's target
// before anything was sent. The report carries no URL or host, and neither does the notice.

export const REASON_EGRESS_REFUSED = "egress_refused";
// A configuration gap of this Workspace, not a source-system failure.
export const REASON_OWN_CONNECTION_INCOMPLETE = "own_connection_incomplete";

export type ReasonNotice = { code: string; title: string; text: string };

const NOTICES: Record<string, Omit<ReasonNotice, "code">> = {
  [REASON_EGRESS_REFUSED]: {
    title: "Outbound connection refused by the egress policy",
    text:
      "The connection's host resolves to a loopback, link-local, private or metadata address, or does not resolve, " +
      "so no request was sent. Point the Workspace's tool connection at a public host.",
  },
  [REASON_OWN_CONNECTION_INCOMPLETE]: {
    title: "This Workspace's own connection is incomplete",
    text:
      "The Workspace uses its own connection for this source, but its URL, sign-in method or credential is missing, " +
      "so nothing was read. Complete it under Workspace settings → Connectors, or switch the Workspace to the global connection.",
  },
};

export function reasonNotice(reason: string | null | undefined): ReasonNotice | null {
  if (!reason) return null;
  const notice = NOTICES[reason];
  return notice ? { code: reason, ...notice } : null;
}


// The notice a run report shows: the run's own reason first, else the first item reason that has one.
export function runReasonNotice(runReason: string | null | undefined, itemReasons: Array<string | null | undefined>): ReasonNotice | null {
  return reasonNotice(runReason) ?? itemReasons.map(reasonNotice).find((notice) => notice !== null) ?? null;
}
