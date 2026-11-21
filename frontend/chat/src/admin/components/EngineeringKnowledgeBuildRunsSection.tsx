import { Fragment, useState } from "react";
import type { Dispatch, SetStateAction } from "react";

import {
  ENGINEERING_KNOWLEDGE_COORDINATES,
  type EngineeringKnowledgeBuildVersions,
  type EngineeringKnowledgeCoordinate,
  hasEngineeringKnowledgeTargetVersion,
} from "./engineeringKnowledgeBuildRequest";
import { statusBadge } from "./engineeringKnowledgeStatusBadge";
import type { AdminKnowledgeTabProps } from "./knowledgeTypes";
import { formatDate } from "../utils/dateTime";

// ─── Build Runs ─────────────────────────────────────────────────────────────

export function BuildRunsSection({
  runs,
  busy,
  onCreateRun,
  versions,
  setVersions,
  allowNetwork,
  setAllowNetwork,
  error,
}: {
  runs: AdminKnowledgeTabProps["engineeringKnowledgeBuildRuns"];
  busy: boolean;
  onCreateRun: () => Promise<void>;
  versions: EngineeringKnowledgeBuildVersions;
  setVersions: Dispatch<SetStateAction<EngineeringKnowledgeBuildVersions>>;
  allowNetwork: boolean;
  setAllowNetwork: (v: boolean) => void;
  error: string | null;
}) {
  const canRun = !busy && hasEngineeringKnowledgeTargetVersion(versions);
  const setVersion = (
    coordinate: EngineeringKnowledgeCoordinate,
    side: "source" | "target",
    value: string,
  ) =>
    setVersions((current) => ({
      ...current,
      [coordinate]: { ...current[coordinate], [side]: value },
    }));

  return (
    <details className="knowledge-entry">
      <RunsSummary runCount={runs.length} busy={busy} canRun={canRun} onCreateRun={onCreateRun} />
      <div style={{ padding: "0.75rem" }}>
        {/* Builder form */}
        <BuilderForm
          versions={versions}
          setVersion={setVersion}
          canRun={canRun}
          onCreateRun={onCreateRun}
          allowNetwork={allowNetwork}
          setAllowNetwork={setAllowNetwork}
          error={error}
        />

        {/* Runs list */}
        <RunsList runs={runs} />
      </div>
    </details>
  );
}

type VersionGridProps = {
  versions: EngineeringKnowledgeBuildVersions;
  setVersion: (coordinate: EngineeringKnowledgeCoordinate, side: "source" | "target", value: string) => void;
  canRun: boolean;
  onCreateRun: () => Promise<void>;
};

type BuildRun = AdminKnowledgeTabProps["engineeringKnowledgeBuildRuns"][number];

function BuilderForm({
  versions,
  setVersion,
  canRun,
  onCreateRun,
  allowNetwork,
  setAllowNetwork,
  error,
}: VersionGridProps & {
  allowNetwork: boolean;
  setAllowNetwork: (v: boolean) => void;
  error: string | null;
}) {
  return (
    <div
      style={{
        marginBottom: "0.8rem",
        display: "flex",
        flexDirection: "column",
        gap: "0.5rem",
      }}
    >
      <VersionGrid versions={versions} setVersion={setVersion} canRun={canRun} onCreateRun={onCreateRun} />
      <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
        <select
          className="connector-field__input"
          style={{ fontSize: "var(--ds-text-xs)", minWidth: "140px" }}
          value={allowNetwork ? "enabled" : "metadata-only"}
          onChange={(e) => setAllowNetwork(e.target.value === "enabled")}
        >
          <option value="metadata-only">Metadata only</option>
          <option value="enabled">Acquire sources</option>
        </select>
      </div>
      {error && (
        <div style={{ fontSize: "var(--ds-text-xs)", color: "var(--status-error)" }}>{error}</div>
      )}
    </div>
  );
}

function RunsList({ runs }: { runs: BuildRun[] }) {
  return runs.length === 0 ? (
    <div
      style={{
        fontSize: "var(--ds-text-xs)",
        color: "var(--text-muted)",
        padding: "0.5rem 0",
      }}
    >
      No builder runs yet.
    </div>
  ) : (
    <div
      style={{ display: "flex", flexDirection: "column", gap: "0.35rem" }}
    >
      {runs.slice(0, 20).map((run) => (
        <RunRow key={run.id} run={run} />
      ))}
    </div>
  );
}

function RunRow({ run }: { run: BuildRun }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: "0.5rem",
        padding: "0.4rem 0.6rem",
        background: "rgba(255,255,255,0.03)",
        borderRadius: "var(--ds-radius-md)",
        fontSize: "var(--ds-text-xs)",
      }}
    >
      {statusBadge(run.status)}
      <span style={{ fontFamily: "monospace" }}>
        {run.stack_key ?? "—"}
      </span>
      <span style={{ color: "var(--text-muted)" }}>
        {Object.entries(run.source_versions || {})
          .map(([k, v]) => `${k}: ${v}`)
          .join(", ") || "—"}
        {" → "}
        {Object.entries(run.target_versions || {})
          .map(([k, v]) => `${k}: ${v}`)
          .join(", ") || "—"}
      </span>
      {run.completed_at && (
        <span
          style={{
            marginLeft: "auto",
            color: "var(--text-muted)",
            fontSize: "var(--ds-text-2xs)",
          }}
        >
          {formatDate(run.completed_at)}
        </span>
      )}
    </div>
  );
}

function RunsSummary({
  runCount,
  busy,
  canRun,
  onCreateRun,
}: {
  runCount: number;
  busy: boolean;
  canRun: boolean;
  onCreateRun: () => Promise<void>;
}) {
  return (
    <summary className="knowledge-entry__summary">
      <span className="knowledge-entry__toggle">Builder Runs</span>
      <span className="knowledge-entry__preview">
        {runCount} run{runCount !== 1 ? "s" : ""}
      </span>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          void onCreateRun();
        }}
        className="admin-panel__action-btn admin-panel__action-btn--primary"
        style={{
          marginLeft: "auto",
          marginRight: "0.5rem",
          fontSize: "var(--ds-text-xs)",
          padding: "0.2rem 0.6rem",
        }}
        disabled={!canRun}
      >
        {busy ? "Building…" : "Run Builder"}
      </button>
    </summary>
  );
}

function VersionGrid({ versions, setVersion, canRun, onCreateRun }: VersionGridProps) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "7rem 1fr 1fr",
        gap: "0.35rem 0.5rem",
        alignItems: "center",
        fontSize: "var(--ds-text-xs)",
      }}
    >
      <span />
      <span style={{ color: "var(--text-muted)" }}>From version</span>
      <span style={{ color: "var(--text-muted)" }}>To version</span>
      {ENGINEERING_KNOWLEDGE_COORDINATES.map(({ key, label }) => (
        <Fragment key={key}>
          <span>{label}</span>
          {(["source", "target"] as const).map((side) => (
            <input
              key={side}
              className="connector-field__input"
              style={{ fontSize: "var(--ds-text-sm)" }}
              aria-label={`${label} ${side === "source" ? "from" : "to"} version`}
              placeholder={side === "source" ? "e.g. 21" : "e.g. 25"}
              value={versions[key][side]}
              onChange={(e) => setVersion(key, side, e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && canRun) void onCreateRun();
              }}
            />
          ))}
        </Fragment>
      ))}
    </div>
  );
}
