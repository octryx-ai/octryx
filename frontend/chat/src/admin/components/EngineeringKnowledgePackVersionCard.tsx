// Engineering knowledge packs: one version in the pack's detail drawer (status, actions, quality, retrieval,
// manifest, source and target versions, source evidence and the first retrievable items).
import { AdminEngineeringKnowledgeRetrievalPanel } from "./AdminEngineeringKnowledgeRetrievalPanel";
import { statusBadge } from "./engineeringKnowledgeStatusBadge";
import type { AdminKnowledgeTabProps } from "./knowledgeTypes";
import type { EngineeringKnowledgePack } from "../types/engineeringKnowledgeTypes";
import { PackVersionActions } from "./EngineeringKnowledgePackVersionActions";
import { VersionQualitySummary } from "./EngineeringKnowledgeVersionQuality";
import { versionQualityBadge } from "./engineeringKnowledgeVersionQualityBadge";
import { ManifestView } from "./EngineeringKnowledgeManifestView";
import { RetrievableItemReview, SourceEvidenceTable } from "./EngineeringKnowledgeEvidence";

type PackVersion = NonNullable<EngineeringKnowledgePack["versions"]>[number];

function PackVersionHeaderRow({ version, ctx }: { version: PackVersion; ctx: AdminKnowledgeTabProps }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: "0.6rem",
        flexWrap: "wrap",
      }}
    >
      <span
        style={{
          fontFamily: "monospace",
          fontSize: "var(--ds-text-sm)",
          fontWeight: 600,
        }}
      >
        v{version.version}
      </span>
      {statusBadge(version.status)}
      {versionQualityBadge(version.quality_status)}
      <span
        style={{
          fontSize: "var(--ds-text-xs)",
          color: "var(--text-muted)",
        }}
      >
        {version.source_count} sources · {version.item_count}{" "}
        items
      </span>
      {version.assignment_count > 0 && (
        <span
          style={{
            fontSize: "var(--ds-text-xs)",
            color: "var(--text-muted)",
          }}
        >
          {version.active_assignment_count} active assignments
        </span>
      )}
      <PackVersionActions
        version={version}
        busy={ctx.engineeringKnowledgeBusy}
        onPublish={ctx.handlePublishEngineeringKnowledgeVersion}
        onAssign={ctx.handleAssignEngineeringKnowledgeVersion}
        onReject={ctx.handleRejectEngineeringKnowledgeVersion}
      />
    </div>
  );
}

function PackVersionEvidence({ version }: { version: PackVersion }) {
  return (
    <>
      <div
        style={{
          marginTop: "0.35rem",
          fontSize: "var(--ds-text-2xs)",
          color: "var(--text-muted)",
        }}
      >
        Sources:{" "}
        {Object.entries(version.source_versions || {})
          .map(([k, v]) => `${k}: ${v}`)
          .join(", ") || "—"}
        {" · "}
        Targets:{" "}
        {Object.entries(version.target_versions || {})
          .map(([k, v]) => `${k}: ${v}`)
          .join(", ") || "—"}
      </div>
      <div style={{ marginTop: "0.55rem" }}>
        <p className="user-edit-panel__section-label">
          Source Evidence
        </p>
        <SourceEvidenceTable sources={version.sources ?? []} />
      </div>
      {(version.items?.length ?? 0) > 0 && (
        <div style={{ marginTop: "0.55rem" }}>
          <p className="user-edit-panel__section-label">
            Retrievable Items
          </p>
          <div style={{ display: "grid", gap: "0.45rem" }}>
            {version.items?.slice(0, 8).map((item) => (
              <RetrievableItemReview
                key={item.id}
                item={item}
              />
            ))}
          </div>
        </div>
      )}
    </>
  );
}

export function PackVersionCard({ pack, version, ctx }: {
  pack: EngineeringKnowledgePack;
  version: PackVersion;
  ctx: AdminKnowledgeTabProps;
}) {
  return (
    <div
      style={{
        border: "1px solid var(--border-soft)",
        borderRadius: "var(--ds-radius-md)",
        padding: "0.65rem 0.8rem",
        background:
          version.status === "draft" ||
          version.status === "pending_review"
            ? "rgba(255,255,255,0.03)"
            : undefined,
      }}
    >
      <PackVersionHeaderRow version={version} ctx={ctx} />
      <VersionQualitySummary version={version} />
      <AdminEngineeringKnowledgeRetrievalPanel
        version={version}
        loading={ctx.engineeringKnowledgeRetrievalLoading}
        result={
          ctx.engineeringKnowledgeRetrievalResults[version.id]
        }
        onSearch={ctx.searchEngineeringKnowledgeRetrievalIndex}
      />
      {version.manifest ? (
        <ManifestView
          manifest={version.manifest}
          packKey={pack.key}
          version={version.version}
        />
      ) : null}
      <PackVersionEvidence version={version} />
    </div>
  );
}
