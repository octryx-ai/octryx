import { useCallback, useEffect, useMemo, useState, type Dispatch, type ReactNode, type SetStateAction } from "react";
import { readJson } from "../utils/adminPanelHelpers";
import { AdminEngineeringKnowledgeExportPreviewPanel } from "./AdminEngineeringKnowledgeExportPreviewPanel";
import {
  AdminEngineeringKnowledgeFederationFeedTable,
  type FederationFeed,
} from "./AdminEngineeringKnowledgeFederationFeedTable";
import {
  AdminEngineeringKnowledgeFederationOperationsPanel,
  type FederationOperations,
} from "./AdminEngineeringKnowledgeFederationOperationsPanel";
import { AdminEngineeringKnowledgeFederationFeedForm } from "./AdminEngineeringKnowledgeFederationFeedForm";
import {
  AdminEngineeringKnowledgeFederationPackagesTable,
  AdminEngineeringKnowledgeFederationSyncRunsTable,
} from "./AdminEngineeringKnowledgeFederationPackageTables";
import {
  DEFAULT_FEED_DRAFT,
  buildFeedPayload,
  type FeedDraft,
  type FederationPackage,
  type FederationPayload,
} from "./engineeringKnowledgeFederationModel";

function StatTile({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="admin-panel__empty-state">
      <span className="admin-panel__eyebrow">{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

type Setter<T> = Dispatch<SetStateAction<T>>;

// One write: saving while it runs, then reload; a failure shows as the panel's error.
async function savingWrite(setSaving: Setter<boolean>, setError: Setter<string | null>, write: () => Promise<unknown>) {
  setSaving(true);
  setError(null);
  try {
    await write();
  } catch (err) {
    setError(err instanceof Error ? err.message : String(err));
  } finally {
    setSaving(false);
  }
}

const reviewBody = (action: string) => JSON.stringify({
  action,
  reason: `Admin ${action.replaceAll("_", " ")} from Federation panel`,
  local_trust_level: action === "accept_lower_trust" ? "silver" : undefined,
});

function ReviewActions({ item, onReview }: { item: FederationPackage; onReview: (packageId: string, action: string) => void }) {
  if (item.direction !== "imported" || item.review_status !== "pending_review") {
    return <span className="admin-panel__hint">-</span>;
  }
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: "0.35rem" }}>
      <button type="button" className="admin-panel__action-btn" onClick={() => onReview(item.id, "accept")}>
        Accept
      </button>
      <button
        type="button"
        className="admin-panel__action-btn"
        onClick={() => onReview(item.id, "accept_lower_trust")}
      >
        Lower trust
      </button>
      <button
        type="button"
        className="admin-panel__action-btn"
        onClick={() => onReview(item.id, "quarantine")}
      >
        Quarantine
      </button>
      <button
        type="button"
        className="admin-panel__action-btn admin-panel__action-btn--danger"
        onClick={() => onReview(item.id, "reject")}
      >
        Reject
      </button>
    </div>
  );
}

function useFederation() {
  const [payload, setPayload] = useState<FederationPayload | null>(null);
  const [draft, setDraft] = useState<FeedDraft>(DEFAULT_FEED_DRAFT);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setPayload(await readJson<FederationPayload>("/admin/chat/api/panel/engineering-knowledge/federation?limit=50"));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const canCreateFeed = useMemo(
    () => draft.name.trim().length > 0 && draft.publisher_instance_id.trim().length > 0,
    [draft.name, draft.publisher_instance_id],
  );

  const createFeed = useCallback(async () => {
    if (!canCreateFeed) return;
    await savingWrite(setSaving, setError, async () => {
      await readJson("/admin/chat/api/panel/engineering-knowledge/federation/feeds", {
        method: "POST",
        body: JSON.stringify(buildFeedPayload(draft)),
      });
      setDraft(DEFAULT_FEED_DRAFT);
      await load();
    });
  }, [canCreateFeed, draft, load]);
  return { payload, draft, setDraft, loading, saving, setSaving, error, setError, load, canCreateFeed, createFeed };
}

export function AdminEngineeringKnowledgeFederationPanel() {
  const { payload, draft, setDraft, loading, saving, setSaving, error, setError, load, canCreateFeed, createFeed } = useFederation();

  const reviewImportPackage = useCallback(
    async (packageId: string, action: string) => {
      await savingWrite(setSaving, setError, async () => {
        await readJson(`/admin/chat/api/panel/engineering-knowledge/federation/packages/${packageId}/review`, {
          method: "POST",
          body: reviewBody(action),
        });
        await load();
      });
    },
    [load, setSaving, setError],
  );

  const disableFeed = useCallback(
    async (feedId: string) => {
      await savingWrite(setSaving, setError, async () => {
        await readJson(`/admin/chat/api/panel/engineering-knowledge/federation/feeds/${feedId}/disable`, {
          method: "POST",
          body: JSON.stringify({ reason: "Emergency disabled from Federation panel" }),
        });
        await load();
      });
    },
    [load, setSaving, setError],
  );

  const renderReviewActions = useCallback(
    (item: FederationPackage) => (
      <ReviewActions item={item} onReview={(packageId, action) => void reviewImportPackage(packageId, action)} />
    ),
    [reviewImportPackage],
  );

  return (
    <div className="admin-panel__section">
      <div className="admin-panel__section-header">
        <div>
          <div className="admin-panel__eyebrow">Engineering Knowledge Federation</div>
          <h3>Publish and subscribe</h3>
        </div>
        <button type="button" className="admin-panel__action-btn" onClick={() => void load()} disabled={loading}>
          Reload
        </button>
      </div>
      {error ? <div className="admin-panel__error">{error}</div> : null}
      {payload ? (
        <FederationOverview payload={payload} draft={draft} setDraft={setDraft} canCreateFeed={canCreateFeed} saving={saving}
          createFeed={createFeed} setError={setError} disableFeed={disableFeed} renderReviewActions={renderReviewActions} />
      ) : loading ? (
        <div className="admin-panel__empty-state">Loading federation state...</div>
      ) : null}
    </div>
  );
}

type OverviewProps = {
  payload: FederationPayload; draft: FeedDraft; setDraft: Setter<FeedDraft>; canCreateFeed: boolean; saving: boolean;
  createFeed: () => Promise<void>; setError: Setter<string | null>; disableFeed: (feedId: string) => Promise<void>;
  renderReviewActions: (item: FederationPackage) => ReactNode;
};

function FederationOverview({
  payload, draft, setDraft, canCreateFeed, saving, createFeed, setError, disableFeed, renderReviewActions,
}: OverviewProps) {
  return (
    <>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
          gap: "0.65rem",
        }}
      >
        <StatTile label="Feeds" value={payload.summary.feed_count} />
        <StatTile label="Packages" value={payload.summary.package_count} />
        <StatTile label="Pending review" value={payload.summary.pending_review_count} />
        <StatTile label="Failed syncs" value={payload.summary.failed_sync_count} />
      </div>

      <AdminEngineeringKnowledgeFederationFeedForm draft={draft} setDraft={setDraft} canCreateFeed={canCreateFeed}
        saving={saving} onCreate={() => void createFeed()} />

      <AdminEngineeringKnowledgeExportPreviewPanel onError={setError} />
      <AdminEngineeringKnowledgeFederationOperationsPanel operations={payload.operations} />

      <h4 style={{ marginTop: "0.9rem" }}>Feeds</h4>
      <AdminEngineeringKnowledgeFederationFeedTable
        feeds={payload.feeds}
        saving={saving}
        onDisableFeed={(feedId) => void disableFeed(feedId)}
      />

      <h4 style={{ marginTop: "0.9rem" }}>Packages</h4>
      <AdminEngineeringKnowledgeFederationPackagesTable packages={payload.packages} renderReviewActions={renderReviewActions} />

      <h4 style={{ marginTop: "0.9rem" }}>Sync runs</h4>
      <AdminEngineeringKnowledgeFederationSyncRunsTable syncRuns={payload.sync_runs} />
    </>
  );
}
