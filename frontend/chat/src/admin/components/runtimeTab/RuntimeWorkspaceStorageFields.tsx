import { RuntimeField, RuntimeSettingsGroup } from "./RuntimeSettingsGroup";
import type { RuntimeTabCtx } from "./types";
// The session folder and whether it is mirrored.
function SessionFolderFields({ ctx }: { ctx: RuntimeTabCtx }) {
  const {
    runtimeWorkspaceBaseDirDraft,
    runtimeWorkspaceStorageBackendDraft,
    setRuntimeWorkspaceBaseDirDraft,
    setRuntimeWorkspaceStorageBackendDraft,
  } = ctx;
  return (
    <>
      <RuntimeField
        id="runtime-ws-base-dir"
        label="Session folder base directory"
        help="Agent file operations and downloaded repositories stay inside the session folder."
        wide
      >
        <input
          id="runtime-ws-base-dir"
          className="admin-panel__input"
          value={runtimeWorkspaceBaseDirDraft}
          onChange={(e) => setRuntimeWorkspaceBaseDirDraft(e.target.value)}
          placeholder="/tmp/octryx-session-workspaces"
        />
      </RuntimeField>
      <RuntimeField
        id="runtime-ws-backend"
        label="Durable storage"
        help="Production S3 access should use pod identity rather than stored credentials."
      >
        <select
          id="runtime-ws-backend"
          className="admin-panel__input"
          value={runtimeWorkspaceStorageBackendDraft}
          onChange={(e) =>
            setRuntimeWorkspaceStorageBackendDraft(e.target.value as "disabled" | "filesystem" | "s3")
          }
        >
          <option value="disabled">Off</option>
          <option value="filesystem">File system</option>
          <option value="s3">Amazon S3</option>
        </select>
      </RuntimeField>
    </>
  );
}

// Where the mirror goes: bucket or root, and the prefix.
function StorageTargetFields({ ctx }: { ctx: RuntimeTabCtx }) {
  const {
    runtimeWorkspaceStorageBucketDraft,
    runtimeWorkspaceStoragePrefixDraft,
    setRuntimeWorkspaceStorageBucketDraft,
    setRuntimeWorkspaceStoragePrefixDraft,
  } = ctx;
  return (
    <>
      <RuntimeField id="runtime-ws-bucket" label="Bucket / root">
        <input
          id="runtime-ws-bucket"
          className="admin-panel__input"
          value={runtimeWorkspaceStorageBucketDraft}
          onChange={(e) => setRuntimeWorkspaceStorageBucketDraft(e.target.value)}
          placeholder="octryx-workspaces"
        />
      </RuntimeField>
      <RuntimeField id="runtime-ws-prefix" label="Prefix">
        <input
          id="runtime-ws-prefix"
          className="admin-panel__input"
          value={runtimeWorkspaceStoragePrefixDraft}
          onChange={(e) => setRuntimeWorkspaceStoragePrefixDraft(e.target.value)}
          placeholder="prod"
        />
      </RuntimeField>
    </>
  );
}

// What is never mirrored, beyond the defaults.
function SyncExclusionFields({ ctx }: { ctx: RuntimeTabCtx }) {
  const {
    runtimeSettings,
    runtimeWorkspaceSyncExcludedDirsDraft,
    runtimeWorkspaceSyncExcludedGlobsDraft,
    setRuntimeWorkspaceSyncExcludedDirsDraft,
    setRuntimeWorkspaceSyncExcludedGlobsDraft,
  } = ctx;
  const defaultDirs: string[] = runtimeSettings?.session_workspace_sync_default_excluded_dirs || [];
  const defaultGlobs: string[] = runtimeSettings?.session_workspace_sync_default_excluded_globs || [];
  return (
    <>
      <RuntimeField
        id="runtime-ws-excluded-dirs"
        label="Extra excluded folders"
        help={`Never mirrored. Always excluded: ${defaultDirs.join(", ") || "none"}.`}
      >
        <input
          id="runtime-ws-excluded-dirs"
          className="admin-panel__input"
          value={runtimeWorkspaceSyncExcludedDirsDraft}
          onChange={(e) => setRuntimeWorkspaceSyncExcludedDirsDraft(e.target.value)}
          placeholder="tmp-cache, reports"
        />
      </RuntimeField>
      <RuntimeField
        id="runtime-ws-excluded-globs"
        label="Extra excluded file patterns"
        help={`Never mirrored. Always excluded: ${defaultGlobs.join(", ") || "none"}.`}
      >
        <input
          id="runtime-ws-excluded-globs"
          className="admin-panel__input"
          value={runtimeWorkspaceSyncExcludedGlobsDraft}
          onChange={(e) => setRuntimeWorkspaceSyncExcludedGlobsDraft(e.target.value)}
          placeholder="*.secret, *.tmp"
        />
      </RuntimeField>
    </>
  );
}

// The size and count limits of the mirror.
function SyncLimitFields({ ctx }: { ctx: RuntimeTabCtx }) {
  const {
    runtimeWorkspaceSyncMaxFileCountDraft,
    runtimeWorkspaceSyncMaxFileSizeDraft,
    setRuntimeWorkspaceSyncMaxFileCountDraft,
    setRuntimeWorkspaceSyncMaxFileSizeDraft,
  } = ctx;
  return (
    <>
      <RuntimeField id="runtime-ws-max-bytes" label="Max mirrored file size (bytes)">
        <input
          id="runtime-ws-max-bytes"
          className="admin-panel__input"
          type="number"
          min={0}
          max={1073741824}
          step={1}
          value={runtimeWorkspaceSyncMaxFileSizeDraft}
          onChange={(e) => setRuntimeWorkspaceSyncMaxFileSizeDraft(e.target.value)}
        />
      </RuntimeField>
      <RuntimeField id="runtime-ws-max-files" label="Max mirrored files">
        <input
          id="runtime-ws-max-files"
          className="admin-panel__input"
          type="number"
          min={0}
          max={100000}
          step={1}
          value={runtimeWorkspaceSyncMaxFileCountDraft}
          onChange={(e) => setRuntimeWorkspaceSyncMaxFileCountDraft(e.target.value)}
        />
      </RuntimeField>
    </>
  );
}

// Where each chat session's working files live and how they are mirrored.
export function RuntimeWorkspaceStorageFields({ ctx }: { ctx: RuntimeTabCtx }) {
  return (
    <RuntimeSettingsGroup
      title="Workspace storage"
      purpose="Each chat session works in its own folder; durable storage mirrors it so files survive pod restarts."
    >
      <div className="admin-form-grid">
        <SessionFolderFields ctx={ctx} />
        <StorageTargetFields ctx={ctx} />
        <SyncExclusionFields ctx={ctx} />
        <SyncLimitFields ctx={ctx} />
      </div>
    </RuntimeSettingsGroup>
  );
}
