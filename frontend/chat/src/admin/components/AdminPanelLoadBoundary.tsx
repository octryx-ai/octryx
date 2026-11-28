import { Component, type ErrorInfo, type ReactNode } from "react";
import { isAdminPanelLoadFailure } from "./adminPanelLoad";

// A rejected React.lazy import is cached, so only a full page reload can load the panel again.

type Props = {
  children: ReactNode;
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
      console.error("Admin panel could not finish loading", error, info);
    }
  }

  private reload = () => {
    if (this.props.onReload) this.props.onReload();
    else window.location.reload();
  };

  render() {
    if (this.state.failed && !isAdminPanelLoadFailure(this.state.error)) {
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
