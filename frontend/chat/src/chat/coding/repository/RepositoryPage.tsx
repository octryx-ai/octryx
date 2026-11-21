import { useState, type ReactNode } from "react";

import { DataTable, type DataTableColumn } from "../../../layout/DataTable";
import { EmptyLine } from "../../../layout/EmptyLine";
import { PageHeader } from "../../../layout/PageHeader";
import { StatusLabel } from "../../../layout/StatusLabel";
import type { RepositoryOverviewRow } from "./repositoryPresenter";
import { RepositoryRunsPanel } from "./RepositoryRunsPanel";

// The Repositories page frame for those without the Work menu: the one page header of the UI, the controls in its
// action row. Inside the Work area the list is the body of the Work page (`embedded`).
export function RepositoryPage({ controls, children, busy = false }: {
  controls: ReactNode; children: ReactNode; busy?: boolean;
}) {
  return <section className="work-area__main repository-page" aria-label="Repositories" aria-busy={busy}>
    <PageHeader eyebrow="Work" title="Repositories" secondary={controls} />
    <div className="work-area__body repository-list">{children}</div>
  </section>;
}

// Every repository the Workspace uses (its records) and every Knowledge git source (workspaceRepositoryRows).
export function RepositoryOverview({ rows, mayAuthor, busy, addSourceHref, onAddForRuns, onConnect, onEditSetup }: {
  rows: RepositoryOverviewRow[];
  mayAuthor: boolean;
  busy: boolean;
  addSourceHref: string;
  // "Add a repository for runs" (alpha): the record a run works in, through a connection; the Knowledge
  // source (addSourceHref) stays the way to search code in Knowledge.
  onAddForRuns?: () => void;
  onConnect: (sourceId: string) => void;
  // Opens Admin › Workspace › Repositories, where the coding setup is edited; without it the summary is text.
  onEditSetup?: () => void;
}) {
  // The repository whose runs are open in the side panel (read only then;).
  const [runsOf, setRunsOf] = useState<RepositoryOverviewRow | null>(null);
  if (!rows.length) {
    return <EmptyLine text="No repository connected yet." testId="repository-list-empty"
      action={onAddForRuns ? { label: "Add a repository for runs", onClick: onAddForRuns }
        : { label: "Add a Knowledge source", href: addSourceHref }} />;
  }
  // Repository / From / Access / Default branch / Coding setup / Source sync: where each row comes from, what agents
  // may do on it and its state in one short label (the sentence is its tooltip); branch and coding setup come from the
  // Workspace's repository record.
  const columns: DataTableColumn<RepositoryOverviewRow>[] = [
    { key: "name", header: "Repository", grow: true, render: (row) => <span title={row.path}>{row.name}</span> },
    { key: "origin", header: "From", nowrap: true, clip: "14rem", render: (row) => <span title={row.originTitle}>{row.origin}</span> },
    { key: "access", header: "Access", nowrap: true, render: (row) => <span title={row.accessTitle}>{row.access}</span> },
    { key: "branch", header: "Default branch", nowrap: true,
      render: (row) => (row.branch ? (
        <>
          <code className="repository-overview__branch">{row.branch}</code>
          {row.branchFromSource ? (
            <span className="repository-overview__branch-from" title="Not stored on the repository record; this is the branch its Knowledge source follows.">
              {" "}from source
            </span>
          ) : null}
        </>
      ) : "–") },
    { key: "setup", header: "Coding setup", nowrap: true, render: (row) => <SetupSummary row={row} onEdit={onEditSetup} /> },
    { key: "status", header: "Source sync", nowrap: true,
      render: (row) => (row.kind === "source"
        ? <StatusLabel label={row.status} tone={row.tone} title={row.statusTitle || undefined} /> : "–") },
  ];
  // A row with a record opens its runs; an author sets up a synced source without a record as a repository for runs.
  const withAction = rows.some((row) => row.recordId || (mayAuthor && row.canSetUp));
  // The add action stays when repositories exist (a Bitbucket repository could not be
  // added once others existed — with rows the page had no way to add one).
  return <>
    <p className="work-area__actions" data-testid="repository-add">
      {onAddForRuns ? <button type="button" className="work-area__button" onClick={onAddForRuns}
        data-testid="repository-add-for-runs">Add a repository for runs</button> : null}
      <a className="work-area__button" href={addSourceHref}>Add a Knowledge source</a>
    </p>
    <DataTable label="Repositories" columns={columns} rows={rows} rowKey={(row) => row.key} testId="repository-overview"
    selectedKey={runsOf?.key ?? null}
    onOpen={(row) => { if (row.recordId) setRunsOf(row); }}
    rowMenu={withAction ? (row) => <RowAction row={row} busy={busy} mayAuthor={mayAuthor}
      onConnect={onConnect} onRuns={() => setRunsOf(row)} /> : undefined} />
    {runsOf ? <RepositoryRunsPanel row={runsOf} onClose={() => setRunsOf(null)} /> : null}
  </>;
}

function SetupSummary({ row, onEdit }: { row: RepositoryOverviewRow; onEdit?: () => void }) {
  if (!row.setup) return <>–</>;
  const label = row.setup.missing ? <StatusLabel label={row.setup.text} tone="attention" /> : row.setup.text;
  if (!onEdit) return <>{label}</>;
  return <button type="button" className="ds-link-button repository-overview__setup" data-testid="repository-setup-edit"
    title="Edit the coding setup in Admin › Workspace › Repositories"
    aria-label={`Coding setup of ${row.name}: ${row.setup.text}. Edit in Admin › Workspace › Repositories`}
    onClick={(event) => { event.stopPropagation(); onEdit(); }}>{label}</button>;
}

function RowAction({ row, busy, mayAuthor, onConnect, onRuns }: {
  row: RepositoryOverviewRow; busy: boolean; mayAuthor: boolean;
  onConnect: (sourceId: string) => void; onRuns: () => void;
}) {
  if (row.recordId) {
    return <button type="button" className="work-area__button" data-testid="repository-runs-open"
      aria-label={`Runs of ${row.name}`} title="The latest workflow runs on this repository" onClick={onRuns}>Runs</button>;
  }
  if (!mayAuthor || !row.canSetUp) return null;
  return <button type="button" className="work-area__button" disabled={busy} data-testid="repository-source-connect"
    aria-label={`Set up ${row.name} for runs`}
    title="Adds this synced Knowledge source as a repository record that workflow runs can use"
    onClick={() => onConnect(row.id)}>Set up for runs</button>;
}
