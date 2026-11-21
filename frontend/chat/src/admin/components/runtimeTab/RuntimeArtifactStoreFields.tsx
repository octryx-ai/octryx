import { useState } from "react";
import type { ReadJsonFn } from "../../hooks/useAdminRuntimeManagement.types";
import { RuntimeField, RuntimeSettingsGroup } from "./RuntimeSettingsGroup";
import type { RuntimeTabCtx } from "./types";

const ARTIFACT_STORE_FIELDS = [
  "artifact_store_backend",
  "artifact_store_bucket",
  "artifact_store_prefix",
  "artifact_store_s3_region",
  "artifact_store_s3_endpoint_url",
] as const;

type ArtifactStoreField = (typeof ARTIFACT_STORE_FIELDS)[number];
type ArtifactStoreDraft = Record<ArtifactStoreField, string>;

function draftFrom(source: Record<string, unknown> | null | undefined): ArtifactStoreDraft {
  const draft = {} as ArtifactStoreDraft;
  for (const field of ARTIFACT_STORE_FIELDS) {
    draft[field] = String(source?.[field] ?? "") || (field === "artifact_store_backend" ? "filesystem" : "");
  }
  return draft;
}

// The draft of the artifact-store fields, changed one field at a time and saved with its own narrow PUT.
function useArtifactStoreDraft(ctx: RuntimeTabCtx) {
  const readJson = ctx.readJson as ReadJsonFn;
  const [draft, setDraft] = useState<ArtifactStoreDraft>(() => draftFrom(ctx.runtimeSettings));
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const change = (field: ArtifactStoreField, value: string) =>
    setDraft((prev) => ({ ...prev, [field]: value }));

  const save = async () => {
    setSaving(true);
    setMessage(null);
    try {
      const updated = await readJson<Record<string, unknown>>("/admin/chat/api/panel/runtime-settings", {
        method: "PUT",
        body: JSON.stringify(draft),
      });
      setDraft(draftFrom(updated));
      setMessage({ tone: "ok", text: "Artifact store settings saved." });
    } catch (err) {
      setMessage({
        tone: "error",
        text: err instanceof Error ? err.message : "Failed to save artifact store settings",
      });
    } finally {
      setSaving(false);
    }
  };

  return { draft, saving, message, change, save };
}

// Large tool artifacts and outputs. Saved on its own with a narrow PUT carrying
// only the artifact-store fields.
export function RuntimeArtifactStoreFields({ ctx }: { ctx: RuntimeTabCtx }) {
  const { draft, saving, message, change, save } = useArtifactStoreDraft(ctx);

  const textField = (field: ArtifactStoreField, label: string, placeholder: string) => (
    <RuntimeField id={`runtime-${field}`} label={label}>
      <input
        id={`runtime-${field}`}
        className="admin-panel__input"
        value={draft[field]}
        onChange={(e) => change(field, e.target.value)}
        placeholder={placeholder}
      />
    </RuntimeField>
  );

  return (
    <RuntimeSettingsGroup
      title="Artifact store"
      purpose="Where large tool artifacts and outputs are kept. S3 and GCS need credentials or pod identity."
    >
      <div className="admin-form-grid">
        <RuntimeField id="runtime-artifact_store_backend" label="Backend">
          <select
            id="runtime-artifact_store_backend"
            className="admin-panel__input"
            value={draft.artifact_store_backend}
            onChange={(e) => change("artifact_store_backend", e.target.value)}
          >
            <option value="filesystem">File system</option>
            <option value="s3">Amazon S3</option>
            <option value="gcs">Google Cloud Storage</option>
          </select>
        </RuntimeField>
        {textField("artifact_store_bucket", "Bucket", "my-artifacts-bucket")}
        {textField("artifact_store_prefix", "Prefix", "artifacts")}
        {textField("artifact_store_s3_region", "S3 region", "us-east-1")}
        {textField("artifact_store_s3_endpoint_url", "S3 endpoint URL (for MinIO)", "https://minio.local:9000")}
      </div>
      {message ? (
        <div
          className={message.tone === "ok" ? "admin-panel__success" : "admin-panel__error"}
          role={message.tone === "ok" ? "status" : "alert"}
        >
          {message.text}
        </div>
      ) : null}
      <div className="admin-panel__form-actions">
        <button
          type="button"
          className="admin-panel__action-btn"
          disabled={saving}
          onClick={() => void save()}
        >
          {saving ? "Saving…" : "Save artifact store"}
        </button>
      </div>
    </RuntimeSettingsGroup>
  );
}
