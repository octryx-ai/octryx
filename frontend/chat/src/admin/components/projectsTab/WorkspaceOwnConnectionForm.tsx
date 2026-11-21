// The own connection form of a Workspace connector: state, health, sign-in fields, Test and Save.
import { AtlassianAuthFields } from "../connectorsTab/AtlassianAuthFields";
import type { AtlassianAuthView } from "../connectorsTab/atlassianAuthView";
import type { AtlassianProduct } from "../connectorsTab/atlassianAuthModes";
import type { AdminConnector } from "../../types/adminPanelTypes.usersProviders";
import { healthText } from "./workspaceConnectionMessages";
import { type WorkspaceConnection } from "./workspaceConnectionTypes";

type Props = {
  product: AtlassianProduct;
  connection: WorkspaceConnection | null;
  storedOwn: boolean;
  asConnector: AdminConnector;
  draft: Record<string, string>;
  view: AtlassianAuthView;
  set: (field: string, value: string) => void;
  attempted: boolean;
  hasErrors: boolean;
  busy: "save" | "test" | "global" | null;
  onTest: () => void;
  onSave: () => void;
};

export function WorkspaceOwnConnectionForm({ product, connection, storedOwn, asConnector, draft, view, set, attempted,
  hasErrors, busy, onTest, onSave }: Props) {
  return (
    <>
      {storedOwn && connection?.stateSummary ? (
        <div
          className="security-field-hint security-field-hint--attention"
          role="note"
          data-testid="workspace-connection-incomplete"
        >
          {connection.stateSummary}
        </div>
      ) : null}
      {storedOwn ? (
        <div
          className="admin-panel__hint"
          data-testid="workspace-connection-health"
        >
          {healthText(connection?.health ?? null)}
        </div>
      ) : null}
      <div className="connector-card__fields">
        <AtlassianAuthFields
          product={product}
          connector={asConnector}
          draft={draft}
          view={view}
          set={set}
          rebind={{ flow: null }}
          showAllErrors={attempted}
        />
      </div>
      <div className="connector-card__actions">
        <button
          type="button"
          className="admin-panel__action-btn"
          disabled={busy !== null}
          onClick={onTest}
        >
          {busy === "test" ? "Testing…" : "Test connection"}
        </button>
        <button
          type="button"
          className="admin-panel__action-btn admin-panel__action-btn--primary"
          disabled={busy !== null}
          onClick={onSave}
        >
          {busy === "save" ? "Saving…" : "Save connection"}
        </button>
      </div>
      <div className="admin-panel__hint">
        Test connection uses what is entered here; a typed secret is used
        for the test only and is not saved. Save connection stores it. Save
        access below changes only enablement and allowlists.
      </div>
      {attempted && hasErrors ? (
        <div className="workspace-connection__message" role="alert">
          Not saved: fix the highlighted fields.
        </div>
      ) : null}
    </>
  );
}
