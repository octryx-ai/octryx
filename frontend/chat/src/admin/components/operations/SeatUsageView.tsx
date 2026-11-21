import { useState, type ReactNode } from "react";

import { DataTable } from "../../../layout/DataTable";
import { EmptyLine } from "../../../layout/EmptyLine";
import { SidePanel } from "../../../layout/SidePanel";
import { StatusLabel } from "../../../layout/StatusLabel";
import { SeatCell } from "../../../chat/cost/SeatCell";
import { callsText, seatAmountText, seatHeading, unpricedHeading, usdText } from "../../../chat/cost/seatEquivalent";
import { TimeText } from "../../utils/TimeText";
import {
  accountTitle,
  allowanceStatus,
  allowanceText,
  limitHitsText,
  seatNote,
  windowText,
  type SeatPerson,
  type SeatUsageReport,
} from "./seatUsageModel";
import type { SeatUsageState } from "./useSeatUsage";

// Operations › Costs › Seats by person: one row per person with what their seat calls would
// cost via the API at list price, their real API cost in its own column, seat calls, calls without a list price and
// limit hits. A row opens the person's seat accounts, models, Workspaces and last allowance in the side panel.

type Row = SeatPerson & { total?: boolean };

export function SeatUsageView({ state }: { state: SeatUsageState }) {
  const [openId, setOpenId] = useState<string | null>(null);
  const { report, error } = state;
  if (error) return <EmptyLine text={error} action={{ label: "Try again", onClick: state.reload }} testId="seat-usage-error" />;

  const labels = report?.labels;
  const total: Row | null = report && report.people.length ? {
    userId: "__total", name: "Total", seat: report.totals.seat, apiCostUsd: report.totals.apiCostUsd,
    seatCalls: report.totals.seatCalls, accounts: [], workspaces: [], allowance: [],
    limitHits: report.people.reduce((sum, person) => sum + person.limitHits, 0), total: true,
  } : null;
  const rows: Row[] = report ? [...report.people, ...(total ? [total] : [])] : [];
  const open = report?.people.find((person) => person.userId === openId) ?? null;

  return (
    <>
      <DataTable<Row>
        label="Seats by person"
        testId="seat-usage-table"
        loading={report === null}
        loadingLabel="seat usage"
        rows={rows}
        rowKey={(row) => row.userId}
        selectedKey={openId}
        onOpen={(row) => { if (!row.total) setOpenId(row.userId); }}
        empty={{ text: "No seat call in this period.", testId: "seat-usage-empty" }}
        columns={[
          { key: "person", header: "Person", grow: true, clip: "20rem",
            render: (row) => <Strong total={row.total}><span title={row.name}>{row.name}</span></Strong> },
          { key: "seat", header: seatHeading(labels), nowrap: true, align: "end",
            render: (row) => <SeatCell figures={{ ...row.seat, unpricedCalls: 0 }} labels={labels} strong={row.total} /> },
          { key: "api", header: "API cost", nowrap: true, align: "end",
            render: (row) => <Strong total={row.total}>{usdText(row.apiCostUsd)}</Strong> },
          { key: "calls", header: "Seat calls", nowrap: true, align: "end",
            render: (row) => <Strong total={row.total}>{String(row.seatCalls)}</Strong> },
          { key: "unpriced", header: unpricedHeading(labels), nowrap: true, align: "end",
            render: (row) => <Strong total={row.total} muted={!row.seat.unpricedCalls}>{String(row.seat.unpricedCalls)}</Strong> },
          { key: "hits", header: "Limit hits", nowrap: true, align: "end",
            render: (row) => <Strong total={row.total} muted={!row.limitHits}>{String(row.limitHits)}</Strong> },
        ]}
      />
      {report ? <p className="ops-muted" data-testid="seat-usage-note">{seatNote(report)}</p> : null}
      {open && report ? <SeatPersonPanel person={open} report={report} onClose={() => setOpenId(null)} /> : null}
    </>
  );
}

function SeatPersonPanel({ person, report, onClose }: { person: SeatPerson; report: SeatUsageReport; onClose: () => void }) {
  const { labels } = report;
  return (
    <SidePanel title={person.name} subtitle={windowText(report)} onClose={onClose} testId="seat-person-panel">
      <dl className="seat-usage__facts">
        <div><dt>{seatHeading(labels)}</dt><dd className="seat-usage__amount">{seatAmountText(person.seat) || "No estimate"}</dd></div>
        {person.seat.unpricedCalls ? (
          <div data-testid="seat-person-unpriced"><dt>{unpricedHeading(labels)}</dt><dd>{callsText(person.seat.unpricedCalls)}</dd></div>
        ) : null}
        <div><dt>API cost, apart</dt><dd>{usdText(person.apiCostUsd)}</dd></div>
        <div><dt>Seat calls</dt><dd>{String(person.seatCalls)}</dd></div>
        <div><dt>Limit hits</dt><dd>{limitHitsText(person.limitHits)}</dd></div>
      </dl>

      <section className="seat-usage__section" aria-label="Seat accounts">
        <h3 className="seat-usage__title">Seat accounts</h3>
        {person.accounts.length ? person.accounts.map((account) => (
          <div className="seat-usage__account" key={account.provider || account.pseudonym} data-testid="seat-account">
            <p className="seat-usage__account-head">
              <span className="seat-usage__account-name">{accountTitle(account)}</span>
              <span className="ops-muted">{callsText(account.calls)}</span>
            </p>
            <DataTable
              label={`Models on ${account.label}`}
              testId="seat-models"
              rows={account.models}
              rowKey={(model) => model.model || model.name}
              empty={{ text: "No model reported." }}
              columns={[
                { key: "model", header: "Model", grow: true, clip: "14rem", render: (model) => <span title={model.model}>{model.name}</span> },
                { key: "seat", header: "Via API (list price)", nowrap: true, align: "end",
                  render: (model) => <SeatCell figures={model.seat} labels={labels} /> },
                { key: "calls", header: "Calls", nowrap: true, align: "end", render: (model) => String(model.calls) },
              ]}
            />
          </div>
        )) : <EmptyLine text="No seat call in this period." />}
      </section>

      <section className="seat-usage__section" aria-label="Workspaces">
        <h3 className="seat-usage__title">Workspaces</h3>
        <DataTable
          label="Workspaces"
          testId="seat-workspaces"
          rows={person.workspaces}
          rowKey={(workspace) => workspace.id || workspace.name}
          empty={{ text: "No Workspace in this period." }}
          columns={[
            { key: "name", header: "Workspace", grow: true, clip: "14rem", render: (workspace) => <span title={workspace.name}>{workspace.name}</span> },
            { key: "seat", header: "Seat via API (list price)", nowrap: true, align: "end",
              render: (workspace) => <SeatCell figures={{ equivalentUsd: workspace.equivalentUsd, unpricedCalls: 0 }} labels={labels} /> },
            { key: "api", header: "API cost", nowrap: true, align: "end", render: (workspace) => usdText(workspace.apiCostUsd) },
          ]}
        />
      </section>

      <section className="seat-usage__section" aria-label="Last allowance">
        <h3 className="seat-usage__title">Last allowance <span className="ops-muted">· information only</span></h3>
        {person.allowance.length ? (
          <ul className="seat-usage__allowance">
            {person.allowance.map((allowance) => {
              const status = allowanceStatus(allowance.status);
              return (
                <li key={allowance.client || allowance.label} data-testid="seat-allowance">
                  <span className="seat-usage__account-name">{allowance.label}</span>
                  <span>{allowanceText(allowance)}</span>
                  {status.label ? <StatusLabel label={status.label} tone={status.tone} /> : null}
                  <TimeText className="ops-muted" value={allowance.updatedAt} fallback="Not known" />
                </li>
              );
            })}
          </ul>
        ) : <EmptyLine text="No allowance reported for this person." />}
      </section>
    </SidePanel>
  );
}

function Strong({ total, muted, children }: { total?: boolean; muted?: boolean; children: ReactNode }) {
  return <span className={`${total ? "ops-strong" : ""}${muted ? " ops-muted" : ""}`.trim() || undefined}>{children}</span>;
}
