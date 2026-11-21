import type { ReactNode } from "react";
import { ACCESS_MODE_LABEL } from "../connectorTypes";
import { accessModeOf } from "../connectorConfig";
import type { SourceConnector } from "../connectorTypes";
import { ActionMenu } from "../../workflowSurfaces/ActionMenu";
import { TimeText } from "../../../utils/TimeText";
import { DataTable } from "../../../../layout/DataTable";
import type { DataTableColumn } from "../../../../layout/DataTable";
import { StatusLabel } from "../../../../layout/StatusLabel";
import type { StatusTone } from "../../../../layout/StatusLabel";
import type { EmptyLineProps } from "../../../../layout/EmptyLine";
import {
  countParts, nameWords, servedItemsText, sourceCadence, sourceContainer, sourceName, sourceOriginLabel, sourceState,
} from "./sourceState";
import type { SourceStateWord } from "./sourceState";
import { sourceMenuItems } from "./sourceRowModel";
import type { SourceActions } from "./sourceRowModel";
import "./knowledge-sources.css";

type SourceRow = { type: "connector"; connector: SourceConnector } | { type: "uploads" };

// Colour only for exceptions (design system): a sync in progress is info, a source that needs someone or whose
// knowledge is out of date is attention; up to date, synced, paused and never synced are plain words.
const TONE: Record<SourceStateWord, StatusTone> = {
  Syncing: "info", "Needs attention": "attention", "Out of date": "attention", "Up to date": "neutral",
  Synced: "neutral", Paused: "neutral", "Never synced": "neutral",
};

// "Reads" takes a quarter of the width; the other columns take what their content needs (see the CSS).
const READS_COLUMN_WIDTH = "25%";

/** Text that wraps only between the given parts, never inside one. */
function Unbroken({ parts }: { parts: string[] }): ReactNode {
  return <>{parts.map((part, index) => <span key={index}>{index ? " " : null}<span className="knowledge-source__nowrap">{part}</span></span>)}</>;
}

// The time and the cadence each stay on one line; on a narrow page the cadence moves under the time.
function LastSync({ connector, at }: { connector: SourceConnector; at: number | null }): ReactNode {
  return <>
    <span className="knowledge-source__nowrap">{at === null ? "—" : <TimeText value={at} />} ·</span>{" "}
    <span className="knowledge-source__nowrap">{sourceCadence(connector)}</span>
  </>;
}

/** The Workspace's sources as one full-width table, then the uploaded documents as their own row. */
export function KnowledgeSourceList({ connectors, selectedKey, busy, runningKey, mayAuthor, actions, schedulingOn = true, empty }: {
  connectors: SourceConnector[]; selectedKey: string | null; busy: boolean; runningKey: string | null;
  mayAuthor: boolean; actions: SourceActions; schedulingOn?: boolean; empty?: EmptyLineProps;
}) {
  if (!connectors.length) {
    return <DataTable<SourceRow> label="Sources" columns={[]} rows={[]} rowKey={() => ""} empty={empty} testId="sources-table" />;
  }
  const rows: SourceRow[] = [...connectors.map((connector) => ({ type: "connector" as const, connector })), { type: "uploads" }];
  const state = (connector: SourceConnector) => sourceState(connector, connector.connector_key === runningKey, schedulingOn);
  // The table fits the page: the source name wraps between words only (never at a hyphen inside
  // one), a count stays with its noun, "Reads" cuts a long address with "…" (the full text in its tooltip), so State
  // always stays visible.
  const columns: DataTableColumn<SourceRow>[] = [
    { key: "name", header: "Source", render: (row) => row.type === "uploads"
      ? <span className="knowledge-source__name-text" data-testid="knowledge-source-uploads">Uploaded documents</span>
      : <strong className="knowledge-source__name" data-testid="knowledge-source" data-source={row.connector.connector_key}><Unbroken parts={nameWords(sourceName(row.connector))} /></strong> },
    { key: "kind", header: "Kind", nowrap: true, render: (row) => row.type === "uploads" ? "Upload" : sourceOriginLabel(row.connector.kind) },
    { key: "scope", header: "Reads", width: READS_COLUMN_WIDTH, render: (row) => {
      const mode = row.type === "uploads" ? null : accessModeOf(row.connector);
      const reads = row.type === "uploads" ? "Files members upload themselves" : sourceContainer(row.connector) || "—";
      return (
        <span className="knowledge-source__reads">
          <span className="knowledge-source__scope" title={reads}>{reads}</span>
          {mode ? <StatusLabel label={ACCESS_MODE_LABEL[mode]} tone="neutral" testId="knowledge-source-access" /> : null}
        </span>
      );
    } },
    { key: "items", header: "Items", align: "end", render: (row) => {
      const items = row.type === "uploads" ? null : servedItemsText(row.connector);
      return items ? <Unbroken parts={countParts(items)} /> : "—";
    } },
    { key: "synced", header: "Last sync", render: (row) => row.type === "uploads" ? "—"
      : <span data-testid="knowledge-source-synced"><LastSync connector={row.connector} at={state(row.connector).lastSyncAt} /></span> },
    { key: "state", header: "State", nowrap: true, render: (row) => {
      if (row.type === "uploads") return null;
      const current = state(row.connector);
      return <StatusLabel label={current.word} tone={TONE[current.word]} title={current.reason ?? undefined} testId="knowledge-source-state" />;
    } },
  ];
  return (
    <DataTable<SourceRow> label="Sources" columns={columns} rows={rows} testId="sources-table"
      rowKey={(row) => row.type === "uploads" ? "__uploads" : row.connector.connector_key}
      selectedKey={selectedKey}
      onOpen={(row) => (row.type === "uploads" ? actions.onOpenUploads() : actions.onShow(row.connector))}
      rowMenu={mayAuthor ? (row) => row.type === "uploads" ? null : (
        <ActionMenu row={{ objectName: sourceName(row.connector) }}
          items={sourceMenuItems(row.connector, { busy, running: row.connector.connector_key === runningKey }, actions)} />
      ) : undefined} />
  );
}
