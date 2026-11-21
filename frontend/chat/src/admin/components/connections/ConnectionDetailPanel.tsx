import { useCallback, useEffect, useMemo, useState } from "react";

import { EmptyLine } from "../../../layout/EmptyLine";
import { LoadingState } from "../../../layout/LoadingState";
import { SidePanel } from "../../../layout/SidePanel";
import { StatusLabel } from "../../../layout/StatusLabel";
import { useConfirmAction } from "../confirm/useConfirmAction";
import { ActionMenu, type ActionMenuItem } from "../workflowSurfaces/ActionMenu";
import type { FieldErrors } from "./ConnectionFields";
import { boundKeysProblem, parseBoundKeys, type UnboundToday } from "./boundScopes";
import { DeviationsTab, ErrorsTab } from "./ConnectionDeviationsTab";
import { AgentToolsTab, KnowledgeUseTab, RepositoriesTab, TicketsUseTab } from "./ConnectionUseTabs";
import { ConnectionOverviewTab } from "./ConnectionOverviewTab";
import { askDeleteConnection, resetConnectionDeviation, runConnectionTest, saveConnection, type ConnectionDetailDeps } from "./connectionDetailActions";
import { loadConnection, syncIntake } from "./connectionsApi";
import { changesOf, draftOf, type ConnectionDraft } from "./connectionDraft";
import {
  accessFieldsOf, bindingOf, findType, isGitType, isTestable, scopeKeyOf, ticketStatesOf, typeLabel, type ConnectionType,
} from "./connectionTypes";
import { stateWord, type ConnectionDetail, type TestResult, type WorkspaceRef } from "./connectionsModel";
import { recentErrorCount } from "./connectionErrors";

// One connection in the side panel (or as a page): Overview (type, access, where it is available), its uses,
// the workspaces that narrow it, and recent errors. "Test" checks the access and every active use. One "Save
// changes" (the footer's only, rightmost action) sends only what changed; a refusal is shown at its field. Secrets are
// never shown. The header's ⋯ menu holds "Connector settings" (the settings page for this connector type) and, last,
// "Delete…" (destructive actions live in the ⋯ menu); it is confirmed and works only without active
// uses, otherwise the server's answer names them.

type Props = {
  id: string; workspaces: WorkspaceRef[]; types: ConnectionType[]; mode: "panel" | "page"; pageHref?: string;
  onClose: () => void; onChanged: () => void; onDeleted?: () => void;
  // Opens the connector settings page on this connection's type.
  onOpenConnectorSettings?: (type: string) => void;
  // Platform admin (presentation only; the server authorizes): only they edit the keys a connection serves.
  isAdmin?: boolean;
};

// The panel's state: the loaded connection, the form's draft and what the last save or test said.
function useConnectionDetailState(id: string, types: ConnectionType[]) {
  const [detail, setDetail] = useState<ConnectionDetail | null | undefined>(undefined);
  const [draft, setDraftState] = useState<ConnectionDraft | null>(null);
  const [tab, setTab] = useState("overview");
  const [errors, setErrors] = useState<FieldErrors>(null);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [testResult, setTestResult] = useState<TestResult | null>(null);
  const [unboundToday, setUnboundToday] = useState<UnboundToday | null>(null);

  const load = useCallback(async () => {
    const next = await loadConnection(id).catch(() => null);
    setDetail(next);
    setDraftState(next ? draftOf(next, scopeKeyOf(next.type, types)) : null);
  }, [id, types]);

  useEffect(() => {
    setDetail(undefined);
    setTestResult(null);
    setErrors(null);
    setNotice("");
    void load();
  }, [load]);

  const before = useMemo(() => (detail ? draftOf(detail, scopeKeyOf(detail.type, types)) : null), [detail, types]);
  return {
    detail, setDetail, draft, setDraftState, tab, setTab, errors, setErrors, notice, setNotice, busy, setBusy,
    testResult, setTestResult, unboundToday, setUnboundToday, load, before,
  };
}

type PanelState = ReturnType<typeof useConnectionDetailState>;

// What the form changed and whether it may be saved.
function connectionEdits(state: PanelState, types: ConnectionType[], isAdmin: boolean) {
  const { detail, draft, before } = state;
  const fields = detail ? accessFieldsOf(findType(types, detail.type)) : [];
  const binding = detail ? bindingOf(detail.type, types) : null;
  const readOnly = !detail?.canEdit;
  const bindingEditable = Boolean(binding) && isAdmin && !readOnly;
  const changes = before && draft && detail
    ? changesOf(before, draft, detail.knowledge?.scope, fields, bindingEditable ? binding : null) : {};
  const dirty = Object.keys(changes).length > 0;
  const keysProblem = binding && draft && bindingEditable ? boundKeysProblem(parseBoundKeys(draft.boundScopes, binding), binding) : "";
  return { fields, binding, readOnly, bindingEditable, changes, dirty, keysProblem };
}

function connectionTabs(detail: ConnectionDetail, types: ConnectionType[]) {
  return [
    { key: "overview", label: "Overview" },
    { key: "knowledge", label: "Knowledge" },
    { key: "tickets", label: "Tickets" },
    { key: "tools", label: "Agent tools" },
    ...(isGitType(detail.type, types) ? [{ key: "repositories", label: "Repositories", count: detail.repositories.length }] : []),
    { key: "deviations", label: "Deviations", count: detail.deviations.length },
    { key: "errors", label: "Errors", count: recentErrorCount(detail) || undefined },
  ];
}

function PanelHeaderActions({ detail, types, state, readOnly, menu, onTest }: {
  detail: ConnectionDetail; types: ConnectionType[]; state: PanelState; readOnly: boolean; menu: ActionMenuItem[]; onTest: () => void;
}) {
  const shownState = state.testResult ? stateWord(state.testResult.state) : stateWord(detail.state);
  const reason = state.testResult ? state.testResult.stateReason : detail.stateReason;
  return (
    <>
      <StatusLabel label={shownState.label} tone={shownState.tone} title={reason || undefined} testId="connection-state" />
      {isTestable(detail.type, types) && !readOnly ? (
        <button type="button" className="admin-panel__action-btn" disabled={state.busy} onClick={onTest}
          data-testid="connection-test">Test</button>
      ) : null}
      {menu.length ? <ActionMenu row={{ objectName: detail.name }} items={menu} /> : null}
    </>
  );
}

function PanelFooter({ notice, disabled, onSave }: { notice: string; disabled: boolean; onSave: () => void }) {
  return (
    <>
      {notice ? <span role="status" className="connections__notice" data-testid="connection-notice">{notice}</span> : null}
      <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" disabled={disabled}
        onClick={onSave} data-testid="connection-save">Save changes</button>
    </>
  );
}

// The tabs other than Overview: the uses, repositories, deviations and errors.
function ConnectionUseTabContent({ tab, detail, types, useProps, onResetDeviation }: {
  tab: string; detail: ConnectionDetail; types: ConnectionType[];
  useProps: Parameters<typeof KnowledgeUseTab>[0];
  onResetDeviation: Parameters<typeof DeviationsTab>[0]["onReset"];
}) {
  return (
    <>
      {tab === "knowledge" ? <KnowledgeUseTab {...useProps} /> : null}
      {tab === "tickets" ? (
        <TicketsUseTab {...useProps} ticketStates={ticketStatesOf(detail.type, types)}
          onSyncIntake={(intake) => syncIntake(intake.workspace?.id ?? "", intake.id)} />
      ) : null}
      {tab === "tools" ? <AgentToolsTab {...useProps} /> : null}
      {tab === "repositories" ? <RepositoriesTab detail={detail} /> : null}
      {tab === "deviations" ? <DeviationsTab detail={detail} onReset={onResetDeviation} /> : null}
      {tab === "errors" ? <ErrorsTab detail={detail} /> : null}
    </>
  );
}

export function ConnectionDetailPanel({
  id, workspaces, types, mode, pageHref, onClose, onChanged, onDeleted, onOpenConnectorSettings, isAdmin = false,
}: Props) {
  const confirm = useConfirmAction();
  const state = useConnectionDetailState(id, types);
  const { detail, draft, load } = state;
  const edits = connectionEdits(state, types, isAdmin);
  const { readOnly } = edits;
  const setDraft = (patch: Partial<ConnectionDraft>) => state.setDraftState((current) => (current ? { ...current, ...patch } : current));
  const deps: ConnectionDetailDeps = { ...state, ...edits, id, types, confirm, onChanged, onDeleted, unboundToday: state.unboundToday };

  const title = detail?.name ?? "Connection";
  if (detail === undefined || (detail && !draft)) {
    return <SidePanel title={title} onClose={onClose} mode={mode} testId="connection-panel"><LoadingState label="the connection" /></SidePanel>;
  }
  if (detail === null || !draft) {
    return (
      <SidePanel title={title} onClose={onClose} mode={mode} testId="connection-panel">
        <EmptyLine text="This connection could not be loaded." action={{ label: "Try again", onClick: () => void load() }} />
      </SidePanel>
    );
  }

  const useProps = { detail, draft, setDraft, readOnly, errors: state.errors };
  const menu: ActionMenuItem[] = [
    ...(onOpenConnectorSettings ? [{ label: "Connector settings", onSelect: () => onOpenConnectorSettings(detail.type), testId: "connection-connector-settings" }] : []),
    ...(readOnly ? [] : [{ label: "Delete…", onSelect: () => askDeleteConnection(deps), danger: true, disabled: state.busy, testId: "connection-delete" }]),
  ];

  return (
    <SidePanel
      title={title}
      subtitle={`${typeLabel(detail.type, types)}${detail.owner.kind === "workspace" && detail.owner.workspace ? ` · owned by ${detail.owner.workspace.name}` : ""}`}
      onClose={onClose}
      mode={mode}
      pageHref={mode === "panel" ? pageHref : undefined}
      testId="connection-panel"
      headerActions={<PanelHeaderActions detail={detail} types={types} state={state} readOnly={readOnly} menu={menu}
        onTest={() => void runConnectionTest(deps)} />}
      tabs={{ tabs: connectionTabs(detail, types), value: state.tab, onChange: state.setTab, label: "Connection", idPrefix: "connection-tab" }}
      footer={readOnly ? null : (
        <PanelFooter notice={state.notice} disabled={!edits.dirty || state.busy || Boolean(edits.keysProblem)}
          onSave={() => void saveConnection(deps)} />
      )}
    >
      {state.tab === "overview" ? (
        <ConnectionOverviewTab detail={detail} draft={draft} setDraft={setDraft} types={types} workspaces={workspaces}
          fields={edits.fields} binding={edits.binding} bindingEditable={edits.bindingEditable} readOnly={readOnly}
          errors={state.errors} testResult={state.testResult} isAdmin={isAdmin} onOpenConnectorSettings={onOpenConnectorSettings}
          setUnboundToday={state.setUnboundToday} />
      ) : null}
      <ConnectionUseTabContent tab={state.tab} detail={detail} types={types} useProps={useProps}
        onResetDeviation={(deviation) => resetConnectionDeviation(deps, deviation.workspace.id, detail.id)} />
      {confirm.dialog}
      {confirm.notice}
    </SidePanel>
  );
}
