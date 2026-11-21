// Admin › Knowledge: the engineering knowledge packs list and its build actions.
import { useEffect, useRef, useState } from "react";
import { BuildRunsSection } from "./EngineeringKnowledgeBuildRunsSection";
import { statusBadge } from "./engineeringKnowledgeStatusBadge";
import type { AdminKnowledgeTabProps } from "./knowledgeTypes";
import type { EngineeringKnowledgePack } from "../types/engineeringKnowledgeTypes";
import { LoadingState } from "../../layout/LoadingState";
import { PackDetailDrawer } from "./EngineeringKnowledgePackDetailDrawer";

type PanelProps = {
  ctx: AdminKnowledgeTabProps;
};

// ─── Main Panel ─────────────────────────────────────────────────────────────

export function AdminEngineeringKnowledgePacksPanel({ ctx }: PanelProps) {
  const initializedRef = useRef(false);
  const {
    engineeringKnowledgeBusy,
    engineeringKnowledgeLoading,
    engineeringKnowledgePackTotal,
    engineeringKnowledgePacks,
    handleDeleteEngineeringKnowledgePack,
    loadEngineeringKnowledgePackDetail,
    refreshEngineeringKnowledgePacks,
    selectedEngineeringKnowledgePack,
  } = ctx;

  const [drawerPack, setDrawerPack] = useState<EngineeringKnowledgePack | null>(null);
  const activeDrawerPack =
    drawerPack && selectedEngineeringKnowledgePack?.id === drawerPack.id
      ? selectedEngineeringKnowledgePack
      : drawerPack;

  useEffect(() => {
    if (initializedRef.current) return;
    initializedRef.current = true;
    void refreshEngineeringKnowledgePacks();
  }, [refreshEngineeringKnowledgePacks]);

  return (
    <div>
      {/* Header */}
      <PacksHeader
        total={engineeringKnowledgePackTotal}
        onReload={() => void refreshEngineeringKnowledgePacks()}
      />

      {/* Packs table */}
      <PacksTable
        loading={engineeringKnowledgeLoading}
        packs={engineeringKnowledgePacks}
        busy={engineeringKnowledgeBusy}
        onInspect={(pack) => {
          setDrawerPack(pack);
          void loadEngineeringKnowledgePackDetail(pack.id);
        }}
        onDelete={(pack) => void handleDeleteEngineeringKnowledgePack(pack)}
      />

      {/* Builder + Runs */}
      <BuilderRuns ctx={ctx} />

      {/* Detail drawer */}
      {activeDrawerPack && (
        <PackDetailDrawer
          pack={activeDrawerPack}
          onClose={() => setDrawerPack(null)}
          ctx={ctx}
        />
      )}
    </div>
  );
}

type PackActions = {
  busy: boolean;
  onInspect: (pack: EngineeringKnowledgePack) => void;
  onDelete: (pack: EngineeringKnowledgePack) => void;
};

function PacksTable({
  loading,
  packs,
  busy,
  onInspect,
  onDelete,
}: PackActions & { loading: boolean; packs: EngineeringKnowledgePack[] }) {
  return loading ? (
    <LoadingState label="engineering packs" variant="cards" />
  ) : packs.length === 0 ? (
    <div className="admin-panel__empty">
      No Engineering Knowledge Packs yet. Use the builder below to create
      one.
    </div>
  ) : (
    <div
      className="admin-panel__table-wrap"
      style={{ marginBottom: "1rem" }}
    >
      <table className="admin-panel__table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Stack</th>
            <th>Versions</th>
            <th>Toolchain</th>
            <th>Status</th>
            <th style={{ width: "150px" }}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {packs.map((pack) => (
            <PackRow key={pack.id} pack={pack} busy={busy} onInspect={onInspect} onDelete={onDelete} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PackRow({ pack, busy, onInspect, onDelete }: PackActions & { pack: EngineeringKnowledgePack }) {
  return (
    <tr>
      <td style={{ fontWeight: 600, maxWidth: "200px" }}>
        <span
          style={{
            display: "block",
            maxWidth: "200px",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {pack.name}
        </span>
      </td>
      <td>
        <span className="admin-panel__badge">{pack.stack_key}</span>
      </td>
      <td style={{ fontFamily: "monospace", fontSize: "var(--ds-text-xs)" }}>
        {pack.versions?.length ?? 0}
      </td>
      <td
        style={{
          fontSize: "var(--ds-text-xs)",
          color: "var(--text-secondary)",
        }}
      >
        {Object.keys(pack.toolchain_policy?.profiles ?? {}).join(
          ", ",
        ) || "—"}
      </td>
      <td>{statusBadge(pack.lifecycle_status)}</td>
      <td>
        <div className="admin-inline-actions">
          <button
            type="button"
            className="admin-panel__action-btn"
            style={{ fontSize: "var(--ds-text-xs)" }}
            onClick={() => onInspect(pack)}
          >
            Inspect
          </button>
          <button
            type="button"
            className="admin-panel__danger-btn"
            style={{ fontSize: "var(--ds-text-xs)" }}
            disabled={busy}
            onClick={() => onDelete(pack)}
          >
            Delete
          </button>
        </div>
      </td>
    </tr>
  );
}

function PacksHeader({ total, onReload }: { total: number; onReload: () => void }) {
  return (
    <div
      className="admin-panel__section-header"
      style={{ marginBottom: "0.6rem" }}
    >
      <span>
        Engineering Packs
        <span
          className="admin-panel__cell--muted"
          style={{ fontWeight: 400, marginLeft: "0.5rem" }}
        >
          ({total} packs)
        </span>
      </span>
      <button
        type="button"
        className="admin-panel__action-btn"
        onClick={onReload}
      >
        Reload
      </button>
    </div>
  );
}

function BuilderRuns({ ctx }: PanelProps) {
  return (
    <div className="task-list">
      <BuildRunsSection
        runs={ctx.engineeringKnowledgeBuildRuns}
        busy={ctx.engineeringKnowledgeBusy}
        onCreateRun={ctx.handleCreateEngineeringKnowledgeBuildRun}
        versions={ctx.engineeringKnowledgeBuildVersions}
        setVersions={ctx.setEngineeringKnowledgeBuildVersions}
        allowNetwork={ctx.engineeringKnowledgeAllowNetwork}
        setAllowNetwork={ctx.setEngineeringKnowledgeAllowNetwork}
        error={ctx.engineeringKnowledgeError}
      />
    </div>
  );
}
