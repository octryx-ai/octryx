// Error boundary around the flow canvas so a React Flow crash shows a short message instead of propagating.
import { Component, type ErrorInfo, type ReactNode } from "react";

// Lightweight error boundary to prevent React Flow crashes from propagating
export class FlowCanvasBoundary extends Component<
  { children: ReactNode; className?: string },
  { hasError: boolean }
> {
  state = { hasError: false };
  static getDerivedStateFromError() {
    return { hasError: true };
  }
  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("[FlowCanvas] Render error:", error, errorInfo);
  }
  render() {
    if (this.state.hasError) {
      return (
        <div
          style={{
            padding: 16,
            color: "var(--muted)",
            fontSize: "var(--ds-text-sm)",
            textAlign: "center",
          }}
        >
          Canvas failed to render. Try switching modes or reloading.
        </div>
      );
    }
    return this.props.children;
  }
}
