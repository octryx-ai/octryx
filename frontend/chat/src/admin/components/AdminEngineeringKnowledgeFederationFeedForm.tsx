// The "Register feed" form of the engineering knowledge federation panel.
import type { Dispatch, SetStateAction } from "react";
import type { FeedDraft } from "./engineeringKnowledgeFederationModel";

type Props = {
  draft: FeedDraft;
  setDraft: Dispatch<SetStateAction<FeedDraft>>;
  canCreateFeed: boolean;
  saving: boolean;
  onCreate: () => void;
};

export function AdminEngineeringKnowledgeFederationFeedForm({ draft, setDraft, canCreateFeed, saving, onCreate }: Props) {
  return (
    <section className="admin-panel__form" style={{ marginTop: "0.9rem" }}>
      <div className="admin-panel__section-header">
        <span className="admin-panel__section-title">Register feed</span>
        <button
          type="button"
          className="admin-panel__action-btn admin-panel__action-btn--primary"
          onClick={onCreate}
          disabled={!canCreateFeed || saving}
        >
          {saving ? "Creating..." : "Create feed"}
        </button>
      </div>
      <div className="admin-panel__form-grid">
        <label>
          <span className="admin-panel__form-label">Name</span>
          <input
            className="admin-panel__form-input"
            value={draft.name}
            onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))}
            placeholder="Publisher Alpha"
          />
        </label>
        <label>
          <span className="admin-panel__form-label">Type</span>
          <select
            className="admin-panel__form-input"
            value={draft.feed_type}
            onChange={(event) => setDraft((current) => ({ ...current, feed_type: event.target.value }))}
          >
            <option value="subscriber">Subscriber</option>
            <option value="publisher">Publisher</option>
          </select>
        </label>
        <label>
          <span className="admin-panel__form-label">Publisher instance</span>
          <input
            className="admin-panel__form-input"
            value={draft.publisher_instance_id}
            onChange={(event) =>
              setDraft((current) => ({ ...current, publisher_instance_id: event.target.value }))
            }
            placeholder="publisher-alpha"
          />
        </label>
        <label>
          <span className="admin-panel__form-label">Sync mode</span>
          <select
            className="admin-panel__form-input"
            value={draft.sync_mode}
            onChange={(event) => setDraft((current) => ({ ...current, sync_mode: event.target.value }))}
          >
            <option value="manual">Manual</option>
            <option value="polling">Polling</option>
            <option value="webhook">Webhook</option>
          </select>
        </label>
        <label>
          <span className="admin-panel__form-label">Endpoint URL</span>
          <input
            className="admin-panel__form-input"
            value={draft.endpoint_url}
            onChange={(event) => setDraft((current) => ({ ...current, endpoint_url: event.target.value }))}
            placeholder="https://publisher.example.invalid/knowledge/feed"
          />
        </label>
        <label>
          <span className="admin-panel__form-label">Signing key ref</span>
          <input
            className="admin-panel__form-input"
            value={draft.signing_key_ref}
            onChange={(event) => setDraft((current) => ({ ...current, signing_key_ref: event.target.value }))}
            placeholder="secret://engineering-knowledge/local-signing"
          />
        </label>
        <label>
          <span className="admin-panel__form-label">Verification key ref</span>
          <input
            className="admin-panel__form-input"
            value={draft.verification_key_ref}
            onChange={(event) =>
              setDraft((current) => ({ ...current, verification_key_ref: event.target.value }))
            }
            placeholder="secret://engineering-knowledge/publisher-alpha"
          />
        </label>
      </div>
    </section>
  );
}
