import { useState } from "react";

import { TimeText } from "../../utils/TimeText";
import { DataTable } from "../../../layout/DataTable";
import { EmptyLine } from "../../../layout/EmptyLine";
import { SegmentedTabs } from "../../../layout/SegmentedTabs";
import { StatusLabel } from "../../../layout/StatusLabel";
import { Field, type FieldErrors } from "./ConnectionFields";
import { PairsEditor, ScheduleSelect, ScopeEditor } from "./ConnectionUseEditors";
import { STATUS_MAP_LABELS, WRITE_BACK_LABELS, type ConnectionDraft } from "./connectionDraft";
import { scheduleText, type TicketState } from "./connectionTypes";
import { connectionToolLabel, rulesHrefFor, scopeText, writeBackHrefFor, type ConnectionDetail, type Intake, type ToolLevel } from "./connectionsModel";
import { addRepositoryFromConnectionHref } from "../workspaceKnowledge/sourceLinks";

const GIT_CONNECTION_TYPES = new Set(["bitbucket", "github", "gitlab", "azure_devops"]);

// The uses of one connection: Knowledge, Tickets, Agent tools and, for git types, Repositories. Each shows
// what the connection does there; switching a use on or off, its schedule, scope, ticket filter, status mapping
// and write-back are edits of the connection itself (one "Save changes", arrays replaced as a whole).

type UseProps = {
  detail: ConnectionDetail; draft: ConnectionDraft; setDraft: (patch: Partial<ConnectionDraft>) => void;
  readOnly: boolean; errors: FieldErrors;
};

function UseSwitch({ label, checked, readOnly, onChange, testId }: {
  label: string; checked: boolean; readOnly: boolean; onChange: (value: boolean) => void; testId: string;
}) {
  return (
    <label className="admin-panel__checkbox connections__check">
      <input type="checkbox" checked={checked} disabled={readOnly} onChange={(event) => onChange(event.target.checked)} data-testid={testId} />
      <span>{label}</span>
    </label>
  );
}

export function KnowledgeUseTab({ detail, draft, setDraft, readOnly, errors }: UseProps) {
  const knowledge = detail.knowledge;
  return (
    <div className="connections__tab" data-testid="connection-tab-knowledge">
      <UseSwitch label="Use for Knowledge" checked={draft.knowledgeEnabled} readOnly={readOnly}
        onChange={(value) => setDraft({ knowledgeEnabled: value })} testId="connection-knowledge-enabled" />
      {draft.knowledgeEnabled ? (
        <>
          {draft.knowledgeScopeKey ? (
            <ScopeEditor scopeKey={draft.knowledgeScopeKey} value={draft.knowledgeScope} readOnly={readOnly} errors={errors}
              onChange={(value) => setDraft({ knowledgeScope: value })} />
          ) : <p className="connections__fact">Reads: {scopeText(knowledge?.scope)}</p>}
          <ScheduleSelect value={draft.knowledgeSchedule} cron={draft.knowledgeCron} path="uses.knowledge.schedule" errors={errors}
            readOnly={readOnly} onChange={(value) => setDraft({ knowledgeSchedule: value })}
            onCronChange={(value) => setDraft({ knowledgeCron: value })} />
          {knowledge ? (
            <p className="connections__fact">
              Last sync: {knowledge.lastSyncAt ? <TimeText value={knowledge.lastSyncAt} mode="recent" /> : "never"}
              {knowledge.lastSyncState ? <> · <StatusLabel label={knowledge.lastSyncState === "ok" ? "Up to date" : knowledge.lastSyncState} /></> : null}
              {knowledge.items !== null ? ` · ${knowledge.items} items` : ""}
              {" · "}<a href="/chat?area=knowledge&tab=workspaceKnowledge">Open Sources</a>
            </p>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

function IntakeRows({ intakes, onSync }: { intakes: Intake[]; onSync: (intake: Intake) => Promise<string> }) {
  const [notes, setNotes] = useState<Record<string, string>>({});
  const sync = async (intake: Intake) => {
    setNotes((current) => ({ ...current, [intake.id]: "Syncing…" }));
    const note = await onSync(intake);
    setNotes((current) => ({ ...current, [intake.id]: note }));
  };
  return (
    <DataTable<Intake>
      label="Intakes" testId="connection-intakes" rows={intakes} rowKey={(intake) => intake.id}
      empty={{ text: "No intake uses this connection yet." }}
      columns={[
        { key: "name", header: "Intake", grow: true, render: (intake) => intake.name || "—" },
        { key: "workspace", header: "Workspace", render: (intake) => intake.workspace?.name ?? "—" },
        { key: "schedule", header: "Schedule", nowrap: true, render: (intake) => (intake.enabled ? scheduleText(intake.schedule) : "Off") },
        { key: "last", header: "Last sync", nowrap: true, render: (intake) => (
          <>{intake.lastSyncAt ? <TimeText value={intake.lastSyncAt} mode="recent" /> : "never"}
            {intake.lastSyncStatus && intake.lastSyncStatus !== "ok" ? <> · <StatusLabel label={intake.lastSyncStatus} /></> : null}</>
        ) },
        { key: "sync", header: "", nowrap: true, align: "end", render: (intake) => (
          <span className="connections__sync">
            {notes[intake.id] ? <span role="status">{notes[intake.id]}</span> : null}
            {intake.workspace ? (
              <button type="button" className="admin-panel__action-btn" onClick={() => void sync(intake)}
                data-testid={`intake-sync-${intake.id}`}>Sync now</button>
            ) : null}
          </span>
        ) },
      ]}
    />
  );
}

export function TicketsUseTab({ detail, draft, setDraft, readOnly, errors, onSyncIntake, ticketStates = [] }: UseProps & {
  onSyncIntake: (intake: Intake) => Promise<string>; ticketStates?: TicketState[];
}) {
  const tickets = detail.tickets;
  return (
    <div className="connections__tab" data-testid="connection-tab-tickets">
      <UseSwitch label="Use for Tickets" checked={draft.ticketsEnabled} readOnly={readOnly}
        onChange={(value) => setDraft({ ticketsEnabled: value })} testId="connection-tickets-enabled" />
      {draft.ticketsEnabled ? (
        <>
          {readOnly ? (
            tickets?.filter ? <p className="connections__fact">Filter: <code>{tickets.filter}</code></p> : null
          ) : (
            <Field label="Which tickets" path="uses.tickets.filter" errors={errors}>
              <input className="admin-panel__input" value={draft.ticketsFilter} placeholder="e.g. project = OPS AND statusCategory != Done"
                onChange={(event) => setDraft({ ticketsFilter: event.target.value })} data-testid="connection-tickets-filter" />
            </Field>
          )}
          <ScheduleSelect value={draft.ticketsSchedule} cron={draft.ticketsCron} path="uses.tickets.schedule" errors={errors}
            readOnly={readOnly} onChange={(value) => setDraft({ ticketsSchedule: value })}
            onCronChange={(value) => setDraft({ ticketsCron: value })} />
          <h4 className="connections__subhead">Status mapping</h4>
          <PairsEditor rows={draft.statusMap} labels={STATUS_MAP_LABELS} path="uses.tickets.status_map" readOnly={readOnly}
            errors={errors} onChange={(rows) => setDraft({ statusMap: rows })} testId="connection-status-map" states={ticketStates} />
          <WriteBackSection detail={detail} ticketStates={ticketStates} />
          <h4 className="connections__subhead">Intakes</h4>
          <IntakeRows intakes={tickets?.intakes ?? []} onSync={onSyncIntake} />
        </>
      ) : null}
    </div>
  );
}

/**
 * Write-back is the Workspace's work item workflow's, not the connection's (422 write_back_on_workflow): shown
 * read-only with a link to where it is changed; never part of the save.
 */
function WriteBackSection({ detail, ticketStates }: { detail: ConnectionDetail; ticketStates: TicketState[] }) {
  const writeBack = detail.tickets?.writeBack;
  const workspaceId = detail.tickets?.intakes.length === 1 ? detail.tickets.intakes[0].workspace?.id ?? "" : "";
  const stateLabel = (key: string) => ticketStates.find((state) => state.key === key)?.label ?? key;
  return (
    <div className="connections__write-back" data-testid="connection-write-back">
      <h4 className="connections__subhead">Write back</h4>
      {writeBack?.enabled && writeBack.transitions.length ? (
        <DataTable<{ ours: string; source: string }>
          label="Write back" testId="connection-write-back-table" rows={writeBack.transitions} rowKey={(row) => `${row.ours}:${row.source}`}
          columns={[
            { key: "ours", header: WRITE_BACK_LABELS.left, grow: true, render: (row) => stateLabel(row.ours) },
            { key: "source", header: WRITE_BACK_LABELS.right, render: (row) => row.source },
          ]}
        />
      ) : <EmptyLine text="Changes here are not written back to the source." testId="connection-write-back-off" />}
      <p className="connections__fact">
        Write-back is set in the Workspace's work item workflow.{" "}
        <a href={writeBackHrefFor(workspaceId)} data-testid="connection-write-back-link">Change in the workflow</a>
      </p>
    </div>
  );
}

const LEVEL_TABS = [{ key: "off", label: "Off" }, { key: "read", label: "Read" }, { key: "write", label: "Read and write" }];

export function AgentToolsTab({ detail, draft, setDraft, readOnly }: UseProps) {
  return (
    <div className="connections__tab" data-testid="connection-tab-tools">
      {readOnly ? (
        <p className="connections__fact">Agents may: {LEVEL_TABS.find((tab) => tab.key === draft.toolLevel)?.label}</p>
      ) : (
        <SegmentedTabs label="What agents may do" tabs={LEVEL_TABS} value={draft.toolLevel} idPrefix="connection-level"
          onChange={(key) => setDraft({ toolLevel: key as ToolLevel })} testId="connection-tool-level" />
      )}
      <DataTable<{ name: string; level: ToolLevel }>
        label="Tools" testId="connection-tools" rows={detail.agentTools?.tools ?? []} rowKey={(tool) => tool.name}
        empty={{ text: "This connection offers agents no tools." }}
        columns={[
          // Readable, with the function name as tooltip.
          { key: "name", header: "Tool", grow: true, render: (tool) => <span title={tool.name}>{connectionToolLabel(tool.name, detail.type)}</span> },
          { key: "level", header: "Kind", nowrap: true, render: (tool) => (tool.level === "write" ? "Writes" : tool.level === "read" ? "Reads" : "Off") },
        ]}
      />
      <p className="connections__fact"><a href={rulesHrefFor(detail.id)} data-testid="connection-approval-rules">Tool &amp; approval policies</a></p>
    </div>
  );
}

export function RepositoriesTab({ detail }: { detail: ConnectionDetail }) {
  return (
    <div className="connections__tab" data-testid="connection-tab-repositories">
      <DataTable<ConnectionDetail["repositories"][number]>
        label="Repositories" testId="connection-repositories" rows={detail.repositories} rowKey={(repo) => repo.name}
        empty={{ text: "No repository uses this connection yet." }}
        columns={[
          { key: "name", header: "Repository", grow: true, render: (repo) => repo.name },
          { key: "build", header: "Build", render: (repo) => repo.build || "—" },
          { key: "test", header: "Test", render: (repo) => repo.test || "—" },
          { key: "owners", header: "Reviewers", render: (repo) => repo.owners.join(", ") || "—" },
          { key: "branch", header: "Branch rule", render: (repo) => repo.branchRule || "—" },
        ]}
      />
      {GIT_CONNECTION_TYPES.has(detail.type) ? (
        <p className="connections__fact">
          <a href={addRepositoryFromConnectionHref("", detail.id)} data-testid="connection-add-repository">
            Add a repository from this connection
          </a>
        </p>
      ) : null}
    </div>
  );
}
