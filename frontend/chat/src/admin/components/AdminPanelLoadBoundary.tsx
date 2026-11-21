import { Component, type ErrorInfo, type ReactNode } from "react";
import { isAdminPanelLoadFailure } from "./adminPanelLoad";

// Recovery for an admin panel that could not finish loading. Every admin panel is a
// React.lazy chunk. Its import rejects when the chunk request fails (network drop, rate limit, a
// redeploy that removed the old hashed files) and also when the module throws while it evaluates;
// the browser does not say which, so the page does not claim a cause. React.lazy keeps the
// rejection. A boundary per panel keeps the error inside the panel, navigation stays usable.
//
// - `lazyAdminPanel` (adminPanelLoad.ts) marks only an import rejection as a panel load failure.
// - `AdminPanelLoadBoundary` (one per panel, keyed by the tab) shows that failure in place of the
//   panel only, with one explicit reload action. The navigation stays mounted; other panels are
//   not promised to work, since they may share a failed dependency. Any other error (a genuine
//   render error) is re-thrown to the area's existing boundary unchanged.
// There is no retry: a cached rejected React.lazy cannot load again without a page reload, so the
// only action is a real reload of the current URL (area, tab and workspace stay in the address).

type Props = {
  children: ReactNode;
  // Reloads the current page; replaceable in tests. Only called when the user chooses it.
  onReload?: () => void;
};

type State = { failed: boolean; error: unknown };

export class AdminPanelLoadBoundary extends Component<Props, State> {
  state: State = { failed: false, error: null };

  static getDerivedStateFromError(error: unknown): State {
    return { failed: true, error };
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    if (isAdminPanelLoadFailure(error)) {
      // The cause stays in the console for support; it is never shown in the page.
      console.error("Admin panel could not finish loading", error, info);
    }
  }

  private reload = () => {
    if (this.props.onReload) this.props.onReload();
    else window.location.reload();
  };

  render() {
    if (this.state.failed && !isAdminPanelLoadFailure(this.state.error)) {
      // Not a load failure: hand it to the area boundary.
      throw this.state.error;
    }
    if (this.state.failed) {
      return (
        <div className="admin-panel__error" role="alert" data-testid="admin-panel-load-failure">
          <strong>This page could not finish loading</strong>
          <p>
            This can happen after an update or a connection problem. You can choose another page from the navigation or reload.
          </p>
          <p>Reloading opens this page again and may discard unsaved changes.</p>
          <button type="button" className="admin-panel__action-btn" onClick={this.reload}>
            Reload page
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
