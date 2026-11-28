import { createElement, useEffect, useState } from "react";

// Plain .ts with createElement (no JSX, no CSS import) so every component and its unit-test loader can require it.

type LoadingStateProps = {
  label: string;
  variant?: "table" | "cards" | "page";
  rows?: number;
  // Without it "Try again" reloads the page (a lazy page whose code did not arrive).
  onRetry?: () => void;
  timeoutMs?: number;
};

export const LOADING_TIMEOUT_MS = 10_000;

export function sentenceStart(label: string): string {
  return label ? label.charAt(0).toUpperCase() + label.slice(1) : label;
}

export function LoadingState({ label, variant = "table", rows = 4, onRetry, timeoutMs = LOADING_TIMEOUT_MS }: LoadingStateProps) {
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    // A sandbox without timers (some unit-test loaders) simply never reaches the slow state.
    if (typeof setTimeout !== "function") return undefined;
    const timer = setTimeout(() => setSlow(true), timeoutMs);
    return () => {
      if (typeof clearTimeout === "function") clearTimeout(timer);
    };
  }, [timeoutMs]);

  if (slow) {
    return createElement(
      "div",
      { className: "loading-state loading-state--slow", role: "status", "data-testid": "loading-slow" },
      createElement("span", null, `${sentenceStart(label)} ${label.endsWith("s") ? "are" : "is"} taking longer than usual.`),
      createElement(
        "button",
        { type: "button", className: "admin-panel__action-btn", onClick: () => (onRetry ? onRetry() : globalThis.location?.reload()) },
        "Try again",
      ),
    );
  }
  return createElement(
    "div",
    { className: `loading-state loading-state--${variant}`, role: "status", "aria-busy": "true", "data-testid": "loading-state" },
    createElement("span", { className: "loading-state__label" }, `Loading ${label}…`),
    ...Array.from({ length: rows }, (_, index) =>
      createElement("div", { key: index, className: "loading-state__block", "aria-hidden": "true" })),
  );
}
