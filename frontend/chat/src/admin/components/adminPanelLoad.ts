// Marks a failed admin panel import. Every admin panel is a React.lazy chunk; the import
// rejects when the chunk request fails (network drop, rate limit, a redeploy that removed the old
// hashed files) or when the module throws while it evaluates, and React.lazy keeps that rejection.
// `lazyAdminPanel` marks only the rejected import, so AdminPanelLoadBoundary can tell it apart from
// a genuine render error; it cannot tell a download failure from an evaluation failure.
import { lazy, type ComponentType } from "react";

const LOAD_FAILURE = Symbol.for("octryx.adminPanelLoadFailure");

type Marked = { [LOAD_FAILURE]?: true };

// The original error object is marked (identity and stack stay intact); a non-object or frozen
// rejection reason is wrapped instead.
function markLoadFailure(cause: unknown): unknown {
  if (typeof cause === "object" && cause !== null) {
    try {
      Object.defineProperty(cause, LOAD_FAILURE, { value: true });
      return cause;
    } catch {
      // Frozen: fall through to the wrapper.
    }
  }
  return { [LOAD_FAILURE]: true, cause };
}

export function isAdminPanelLoadFailure(error: unknown): boolean {
  return typeof error === "object" && error !== null && (error as Marked)[LOAD_FAILURE] === true;
}

// The import with its rejection marked as a load failure; nothing else is marked.
export function markImportFailure<T>(load: () => Promise<T>): () => Promise<T> {
  return () =>
    load().catch((error: unknown) => {
      throw markLoadFailure(error);
    });
}

// React.lazy for an admin panel whose failed download AdminPanelLoadBoundary can recognise.
export function lazyAdminPanel<P>(load: () => Promise<{ default: ComponentType<P> }>) {
  return lazy(markImportFailure(load));
}
