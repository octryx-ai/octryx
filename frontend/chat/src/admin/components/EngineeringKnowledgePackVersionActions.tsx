// The actions of one Engineering Pack version: publish a passed draft, assign a published version, reject a draft.
import type { EngineeringKnowledgePackVersion } from "../types/engineeringKnowledgeTypes";
import type { AdminKnowledgeTabProps } from "./knowledgeTypes";

type PackVersionActionsProps = {
  version: EngineeringKnowledgePackVersion;
  busy: boolean;
  onPublish: AdminKnowledgeTabProps["handlePublishEngineeringKnowledgeVersion"];
  onAssign: AdminKnowledgeTabProps["handleAssignEngineeringKnowledgeVersion"];
  onReject: AdminKnowledgeTabProps["handleRejectEngineeringKnowledgeVersion"];
};

export function PackVersionActions({ version, busy, onPublish, onAssign, onReject }: PackVersionActionsProps) {
  return (
    <div
      style={{
        display: "flex",
        gap: "0.3rem",
        marginLeft: "auto",
      }}
    >
      {(version.status === "draft" ||
        version.status === "pending_review") &&
        version.quality_status === "passed" && (
          <button
            type="button"
            className="admin-panel__action-btn admin-panel__action-btn--primary"
            style={{
              fontSize: "var(--ds-text-2xs)",
              padding: "0.18rem 0.5rem",
            }}
            disabled={busy}
            onClick={() =>
              void onPublish(
                version.id,
              )
            }
          >
            Publish
          </button>
        )}
      {version.status === "published" && (
        <button
          type="button"
          className="admin-panel__action-btn"
          style={{
            fontSize: "var(--ds-text-2xs)",
            padding: "0.18rem 0.5rem",
          }}
          disabled={busy}
          onClick={() =>
            void onAssign(
              version.id,
            )
          }
        >
          Assign Global
        </button>
      )}
      {(version.status === "draft" ||
        version.status === "pending_review") && (
        <button
          type="button"
          className="admin-panel__danger-btn"
          style={{
            fontSize: "var(--ds-text-2xs)",
            padding: "0.18rem 0.5rem",
          }}
          disabled={busy}
          onClick={() =>
            void onReject(
              version.id,
            )
          }
        >
          Reject
        </button>
      )}
    </div>
  );
}
