import { createElement, useEffect, useState } from "react";

// Plain .ts with createElement (no JSX, no CSS import; the stylesheet is styles/chat/loading-state.css), so every
// component and its unit-test loader can require it.

type LoadingStateProps = {
  // What is loading, in the user's words: "work items", "the delivery pipeline".
  label: string;
  // table: rows of a list; cards: a grid of cards; page: a header and a few blocks.
  variant?: "table" | "cards" | "page";
  rows?: number;
  // Loads again; without it "Try again" reloads the page (a lazy page whose code did not arrive).
  onRetry?: () => void;
  timeoutMs?: number;
};

export const LOADING_TIMEOUT_MS = 10_000;

/** "Work items" from "work items": the sentence start of a label. */
export function sentenceStart(label: string): string {
  return label ? label.charAt(0).toUpperCase() + label.slice(1) : label;
}

// The one loading state of the UI: the outline of what is coming instead of a "Loading…" text, and
// after ten seconds a plain message with "Try again". The request keeps running; when it finishes, the content
// replaces this state.
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
