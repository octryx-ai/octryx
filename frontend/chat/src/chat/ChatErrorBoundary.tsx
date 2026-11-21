import { Component, type ErrorInfo, type ReactNode } from "react";
import { isStaleBuildError, reloadForNewBuild } from "../staleBuild";

type ChatErrorBoundaryProps = {
  children: ReactNode;
  fallbackTitle?: string;
  fallbackBody?: string;
};

type ChatErrorBoundaryState = {
  hasError: boolean;
  // Octryx was updated while this tab was open: the old build's parts are gone.
  staleBuild?: boolean;
};

export class ChatErrorBoundary extends Component<
  ChatErrorBoundaryProps,
  ChatErrorBoundaryState
> {
  state: ChatErrorBoundaryState = {
    hasError: false,
  };

  static getDerivedStateFromError(error: unknown): ChatErrorBoundaryState {
    return { hasError: true, staleBuild: isStaleBuildError(error) };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    if (isStaleBuildError(error) && reloadForNewBuild()) return;
    console.error("Chat UI boundary caught an error", error, errorInfo);
  }

  render() {
    if (this.state.hasError && this.state.staleBuild) {
      return (
        <div className="workspace__error workspace__error--boundary" role="alert">
          <strong>Octryx was updated</strong>
          <div>This tab still runs the previous version. Reload to continue with the new one.</div>
          <div><button type="button" className="ds-btn ds-btn--sm" onClick={() => window.location.reload()}>Reload</button></div>
        </div>
      );
    }
    if (this.state.hasError) {
      return (
        <div className="workspace__error workspace__error--boundary">
          <strong>{this.props.fallbackTitle || "Chat UI error"}</strong>
          <div>
            {this.props.fallbackBody ||
              "A rendering error occurred in this panel. Reload the page to recover."}
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
