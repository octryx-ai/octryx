// Engineering knowledge packs: the detail drawer of one pack (versions, sources, items, review).
import { statusBadge } from "./engineeringKnowledgeStatusBadge";
import type { AdminKnowledgeTabProps } from "./knowledgeTypes";
import type { EngineeringKnowledgePack } from "../types/engineeringKnowledgeTypes";
import { PackVersionCard } from "./EngineeringKnowledgePackVersionCard";

// ─── Pack Detail Drawer ──────────────────────────────────────────────────────

function PackDrawerHeader({ pack, onClose }: { pack: EngineeringKnowledgePack; onClose: () => void }) {
  return (
    <div className="user-edit-panel__header">
      <div>
        <p className="user-edit-panel__header-label">Engineering Pack</p>
        <h2 className="user-edit-panel__header-name">{pack.name}</h2>
      </div>
      <button
        type="button"
        className="user-edit-panel__close"
        onClick={onClose}
        aria-label="Close"
      >
        <svg viewBox="0 0 20 20" width="14" height="14" fill="currentColor">
          <path
            d="M5 5l10 10M15 5L5 15"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            fill="none"
          />
        </svg>
      </button>
    </div>
  );
}

// Stack, lifecycle and how many versions there are, one of them published or not.
function PackMetaRow({ pack, versionCount }: { pack: EngineeringKnowledgePack; versionCount: number }) {
  return (
    <div className="user-edit-panel__section">
      <div
        style={{
          display: "flex",
          gap: "0.6rem",
          flexWrap: "wrap",
          alignItems: "center",
        }}
      >
        <span className="admin-panel__badge">{pack.stack_key}</span>
        {statusBadge(pack.lifecycle_status)}
        <span
          style={{
            fontSize: "var(--ds-text-xs)",
            color: "var(--text-muted)",
            marginLeft: "auto",
          }}
        >
          {versionCount} version{versionCount !== 1 ? "s" : ""} ·{" "}
          {pack.latest_published_version_id
            ? "published"
            : "no published version"}
        </span>
      </div>
    </div>
  );
}

function PackToolchainProfiles({ profiles }: { profiles: string[] }) {
  return (
    <div className="user-edit-panel__section">
      <p className="user-edit-panel__section-label">
        Toolchain Profiles
      </p>
      <div
        style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap" }}
      >
        {profiles.map((p) => (
          <span
            key={p}
            className="admin-panel__badge admin-panel__badge--active"
          >
            {p}
          </span>
        ))}
      </div>
    </div>
  );
}

function PackVersionsSection({ pack, versions, ctx }: {
  pack: EngineeringKnowledgePack;
  versions: NonNullable<EngineeringKnowledgePack["versions"]>;
  ctx: AdminKnowledgeTabProps;
}) {
  return (
    <div className="user-edit-panel__section">
      <p className="user-edit-panel__section-label">Versions</p>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: "0.5rem",
        }}
      >
        {versions.map((version) => (
          <PackVersionCard key={version.id} pack={pack} version={version} ctx={ctx} />
        ))}
      </div>
    </div>
  );
}

export function PackDetailDrawer({
  pack,
  onClose,
  ctx,
}: {
  pack: EngineeringKnowledgePack;
  onClose: () => void;
  ctx: AdminKnowledgeTabProps;
}) {
  const versions = pack.versions ?? [];

  const toolchainProfiles = Object.keys(pack.toolchain_policy?.profiles ?? {});

  return (
    <div className="user-edit-panel__backdrop" onClick={onClose}>
      <div
        className="user-edit-panel"
        onClick={(e) => e.stopPropagation()}
        style={{ width: "min(38rem, 95vw)" }}
      >
        <PackDrawerHeader pack={pack} onClose={onClose} />

        <div className="user-edit-panel__body">
          <PackMetaRow pack={pack} versionCount={versions.length} />

          {toolchainProfiles.length > 0 && <PackToolchainProfiles profiles={toolchainProfiles} />}

          {versions.length > 0 && <PackVersionsSection pack={pack} versions={versions} ctx={ctx} />}

          {/* Actions summary */}
          <div
            style={{
              padding: "0.6rem 1.25rem",
              display: "flex",
              gap: "0.5rem",
              justifyContent: "flex-end",
            }}
          >
            <button
              type="button"
              className="admin-panel__action-btn"
              onClick={onClose}
            >
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
