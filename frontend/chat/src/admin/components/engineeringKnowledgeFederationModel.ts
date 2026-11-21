// Engineering knowledge federation: payload types, the feed draft and display helpers of the federation panel.
import type { FederationFeed } from "./AdminEngineeringKnowledgeFederationFeedTable";
import type { FederationOperations } from "./AdminEngineeringKnowledgeFederationOperationsPanel";
import { formatDateTime } from "../utils/dateTime";

export type FederationPackage = {
  id: string;
  feed_name?: string | null;
  direction: string;
  package_id: string;
  publisher_instance_id: string;
  schema_version: string;
  package_checksum: string;
  classification: string;
  trust_level: string;
  status: string;
  review_status: string;
  version: number;
  conflicts: Array<Record<string, unknown>>;
  retraction_refs: Array<Record<string, unknown>>;
  created_at?: string | null;
};

export type FederationSyncRun = {
  id: string;
  feed_name?: string | null;
  operation: string;
  status: string;
  package_id?: string | null;
  errors: Array<{ code?: string; message?: string }>;
  started_at?: string | null;
  completed_at?: string | null;
};

export type FederationPayload = {
  feeds: FederationFeed[];
  packages: FederationPackage[];
  sync_runs: FederationSyncRun[];
  summary: {
    feed_count: number;
    package_count: number;
    pending_review_count: number;
    failed_sync_count: number;
  };
  operations?: FederationOperations;
};

export type FeedDraft = {
  name: string;
  feed_type: string;
  publisher_instance_id: string;
  endpoint_url: string;
  sync_mode: string;
  signing_key_ref: string;
  verification_key_ref: string;
};

export const DEFAULT_FEED_DRAFT: FeedDraft = {
  name: "",
  feed_type: "subscriber",
  publisher_instance_id: "",
  endpoint_url: "",
  sync_mode: "manual",
  signing_key_ref: "",
  verification_key_ref: "",
};
export function statusBadgeClass(status: string) {
  const normalized = status.toLowerCase();
  if (["active", "success", "published", "ready"].includes(normalized)) {
    return "admin-panel__badge admin-panel__badge--active";
  }
  if (["failed", "blocked", "retracted"].includes(normalized)) {
    return "admin-panel__badge admin-panel__badge--danger";
  }
  if (["pending_review", "paused", "retraction_received"].includes(normalized)) {
    return "admin-panel__badge admin-panel__badge--warning";
  }
  return "admin-panel__badge";
}

export function formatDate(value?: string | null) {
  if (!value) return "-";
  return formatDateTime(value);
}

export function shortChecksum(value: string) {
  return value ? `${value.slice(0, 10)}...` : "-";
}

export function buildFeedPayload(draft: FeedDraft) {
  return {
    name: draft.name.trim(),
    feed_type: draft.feed_type,
    publisher_instance_id: draft.publisher_instance_id.trim(),
    endpoint_url: draft.endpoint_url.trim() || null,
    sync_mode: draft.sync_mode,
    signing_key_ref: draft.signing_key_ref.trim() || null,
    verification_key_ref: draft.verification_key_ref.trim() || null,
  };
}
