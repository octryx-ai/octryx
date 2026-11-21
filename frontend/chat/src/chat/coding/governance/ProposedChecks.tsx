import { useCallback, useEffect, useState } from "react";

import { DataTable, type DataTableColumn } from "../../../layout/DataTable";
import { SegmentedTabs } from "../../../layout/SegmentedTabs";
import { StatusLabel } from "../../../layout/StatusLabel";
import { ProposedCheckPanel } from "./ProposedCheckPanel";
import {
  evidenceText, kindLabel, loadProposals, proofStatus, stateStatus, type CheckProposal, type ProposalList, type ProposalState,
} from "./proposedChecksModel";

// Work › Coding rules › Proposed checks (From Correction to Check): what the team corrected twice, as a check
// to approve. Hidden where the platform has no proposals yet (404 not_available).
export function ProposedChecks({ workspaceId }: { workspaceId: string }) {
  const [list, setList] = useState<ProposalList | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [state, setState] = useState<ProposalState>("proposed");
  const [openId, setOpenId] = useState<string | null>(null);
  const [viewerId, setViewerId] = useState("");

  const load = useCallback(async () => {
    try { setList(await loadProposals(workspaceId)); setError(null); } catch (failure) { setError((failure as Error).message); setList(null); }
  }, [workspaceId]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    let current = true;
    void fetch("/api/v1/auth/me", { credentials: "same-origin" }).then((r) => (r.ok ? r.json() : null))
      .then((me: { id?: string } | null) => { if (current && me?.id) setViewerId(me.id); }).catch(() => {});
    return () => { current = false; };
  }, []);

  if (list === undefined && !error) return null;
  if (!list) return error ? <p role="alert" className="work-problems-line work-problems-line--problem">{error}</p> : null;
  const rows = list.items.filter((row) => row.state === state);
  const columns: DataTableColumn<CheckProposal>[] = [
    { key: "check", header: "Check", grow: true, minWidth: "14rem", render: (row) => <span title={row.message.what}>{row.draft.summary}</span> },
    { key: "kind", header: "Kind", nowrap: true,
      render: (row) => <span className="coding-rules__cell" data-label="Kind">{kindLabel(row.draft.kind)}</span> },
    { key: "evidence", header: "Evidence", nowrap: true, clip: "16rem",
      render: (row) => <span className="coding-rules__cell" data-label="Evidence">{evidenceText(row)}</span> },
    { key: "old", header: "Old instances", nowrap: true, align: "end",
      render: (row) => <span className="coding-rules__cell" data-label="Old instances">{row.old_instances.count}</span> },
    { key: "proof", header: "Proof", nowrap: true, render: (row) => {
      const proof = proofStatus(row.proof);
      return <StatusLabel label={proof.label} tone={proof.tone} title={proof.title} />;
    } },
    { key: "state", header: "State", nowrap: true, render: (row) => {
      const shown = stateStatus(row);
      return <StatusLabel label={shown.label} tone={shown.tone} testId={`proposed-check-state-${row.id}`} />;
    } },
  ];
  return <section className="coding-rules coding-rules__proposed" aria-labelledby="proposed-checks-title" data-testid="proposed-checks">
    <div className="coding-rules__proposed-head">
      <h2 id="proposed-checks-title" className="coding-rules__proposed-title">Proposed checks</h2>
      {list.stub ? <span className="admin-panel__hint" title="Sample proposals until the platform records corrections.">sample data</span> : null}
    </div>
    <p className="admin-panel__hint">A mistake the team corrected twice becomes a proposed check. Approved checks run at the end of
      each turn and in the pipeline, as a warning first; the team can switch any of them off.</p>
    <SegmentedTabs label="Proposed checks by state" idPrefix="proposed-checks" size="small" value={state}
      onChange={(key) => setState(key as ProposalState)} testId="proposed-checks-states"
      tabs={(["proposed", "approved", "rejected"] as ProposalState[]).map((key) => ({
        key, label: key[0].toUpperCase() + key.slice(1), count: list.counts[key] ?? 0 }))} />
    <DataTable label="Proposed checks" columns={columns} rows={rows} rowKey={(row) => row.id} selectedKey={openId}
      onOpen={(row) => setOpenId(row.id)} testId="proposed-checks-table"
      empty={{ text: state === "proposed" ? "Nothing to decide: no correction has repeated yet." : `No ${state} checks.` }} />
    {openId ? <ProposedCheckPanel workspaceId={workspaceId} id={openId} viewerId={viewerId} mayApprove={list.may_approve}
      onClose={() => setOpenId(null)} onChanged={() => void load()} /> : null}
  </section>;
}
