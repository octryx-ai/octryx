import { useCallback, useEffect, useState } from "react";

import { SidePanel } from "../../../layout/SidePanel";
import { ConfirmDialog } from "../confirm/ConfirmDialog";
import { ActionMenu } from "../workflowSurfaces/ActionMenu";
import { RestConnections } from "./RestConnections";
import { RestDefinitionDetails } from "./RestDefinitionDetails";
import { RestOperationEditor } from "./RestOperationEditor";
import { RestOperationList } from "./RestOperationList";
import { deleteDefinition, loadDefinition, type RestDefinition, type RestOperation } from "./restApisApi";
import { restErrorView } from "./restErrorsModel";
import { schemeLabel } from "./restAuthModel";
import { serverWarnings } from "./restOperationsModel";
import { FormError, Warnings } from "./restApisParts";
import type { Workspace } from "./RestApisPage";

type Tab = "operations" | "connections" | "details";

// One REST API in the side panel: its warnings on top, then Operations (list → editor with setup, access and test
// call), Connections and Details. Delete is in the "⋯" menu and asks in place.
export function RestApiDetailPanel({ definitionId, workspaces, onClose, onDeleted }: {
  definitionId: string;
  workspaces: Workspace[];
  onClose: () => void;
  onDeleted: () => void;
}) {
  const [definition, setDefinition] = useState<RestDefinition | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("operations");
  const [opId, setOpId] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setDefinition(await loadDefinition(definitionId));
      setError(null);
    } catch (failure) {
      setError(restErrorView(failure).text);
    }
  }, [definitionId]);
  useEffect(() => { void load(); }, [load]);

  const remove = () => removeDefinition({ definitionId, setBusy, setConfirming, setDeleteError, onDeleted });

  const operations = definition?.operations ?? [];
  const operation = operations.find((op) => op.id === opId) ?? null;
  const subtitle = definition ? detailSubtitle(definition, operations) : undefined;

  return (
    <SidePanel
      title={definition?.name ?? "REST API"}
      subtitle={subtitle}
      onClose={onClose}
      testId="rest-detail"
      headerActions={definition ? (
        <ActionMenu row={{ objectName: definition.name }}
          items={[{ label: "Delete REST API…", danger: true, onSelect: () => { setDeleteError(null); setConfirming(true); }, testId: "rest-delete" }]} />
      ) : null}
      tabs={{
        tabs: detailTabs(operations.length),
        value: tab, onChange: (next) => setTab(next as Tab), label: "REST API sections", idPrefix: "rest-detail",
      }}
    >
      <DetailSections definition={definition} error={error} tab={tab} operation={operation} workspaces={workspaces}
        setTab={setTab} setOpId={setOpId} setDefinition={setDefinition} reload={() => void load()} />
      {confirming && definition ? (
        <DeleteApiDialog name={definition.name} operations={operations.length} busy={busy} error={deleteError}
          onConfirm={() => void remove()} onCancel={() => setConfirming(false)} />
      ) : null}
    </SidePanel>
  );
}

// Deletes the API after the confirmation; a refusal stays in the dialog.
async function removeDefinition({ definitionId, setBusy, setConfirming, setDeleteError, onDeleted }: {
  definitionId: string;
  setBusy: (busy: boolean) => void;
  setConfirming: (confirming: boolean) => void;
  setDeleteError: (error: string | null) => void;
  onDeleted: () => void;
}) {
  setBusy(true);
  try {
    await deleteDefinition(definitionId);
    setConfirming(false);
    onDeleted();
  } catch (failure) {
    setDeleteError(restErrorView(failure).text);
  } finally {
    setBusy(false);
  }
}

const detailSubtitle = (definition: RestDefinition, operations: RestOperation[]) =>
  `${definition.key} · ${schemeLabel(definition.auth.scheme)} · ${operations.filter((op) => op.enabled).length} of ${operations.length} operations on`;

const detailTabs = (operations: number) => [
  { key: "operations", label: "Operations", count: operations },
  { key: "connections", label: "Connections" },
  { key: "details", label: "Details" },
];

function DeleteApiDialog({ name, operations, busy, error, onConfirm, onCancel }: {
  name: string; operations: number; busy: boolean; error: string | null; onConfirm: () => void; onCancel: () => void;
}) {
  return (
    <ConfirmDialog title={`Delete ${name}?`} confirmLabel="Delete REST API" busy={busy} error={error}
      onConfirm={onConfirm} onCancel={onCancel}>
      <p>This also removes its {operations} operations and its connections with their stored secrets. Agents lose its tools at once. The audit of its calls is kept.</p>
    </ConfirmDialog>
  );
}

// The panel's body: a load error, the server's warnings (one naming an operation opens it) and the open tab.
function DetailSections({ definition, error, tab, operation, workspaces, setTab, setOpId, setDefinition, reload }: {
  definition: RestDefinition | null;
  error: string | null;
  tab: Tab;
  operation: RestOperation | null;
  workspaces: Workspace[];
  setTab: (tab: Tab) => void;
  setOpId: (opId: string | null) => void;
  setDefinition: (definition: RestDefinition) => void;
  reload: () => void;
}) {
  return (
    <div className="rst-stack">
      <FormError text={error} />
      {/* The server's warnings (backend); one that names an operation opens it. The editor shows its own. */}
      {definition && !(tab === "operations" && operation) ? (
        <Warnings testId="rest-detail-warnings" label="Warnings of this API"
          items={serverWarnings(definition).map(({ text, opId: target }) => ({
            text, onOpen: target ? () => { setTab("operations"); setOpId(target); } : undefined,
          }))} />
      ) : null}
      {definition && tab === "operations" ? (
        operation ? (
          <RestOperationEditor key={operation.id} definition={definition} operation={operation} workspaces={workspaces}
            onBack={() => setOpId(null)} onSaved={reload} onDeleted={() => { setOpId(null); reload(); }} />
        ) : (
          <RestOperationList definition={definition} onOpen={setOpId} onAdded={reload} />
        )
      ) : null}
      {definition && tab === "connections" ? <RestConnections definition={definition} workspaces={workspaces} /> : null}
      {definition && tab === "details" ? (
        <RestDefinitionDetails key={definition.updated_at ?? definition.id} definition={definition} onSaved={setDefinition} />
      ) : null}
    </div>
  );
}
