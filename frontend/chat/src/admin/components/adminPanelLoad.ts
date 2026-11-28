// React.lazy caches a rejected import; the mark lets AdminPanelLoadBoundary tell a load failure from a render error.
import { lazy, type ComponentType } from "react";

const LOAD_FAILURE = Symbol.for("octryx.adminPanelLoadFailure");

type Marked = { [LOAD_FAILURE]?: true };

// Mark the original error so identity and stack stay intact; non-object or frozen reasons are wrapped.
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

export function markImportFailure<T>(load: () => Promise<T>): () => Promise<T> {
  return () =>
    load().catch((error: unknown) => {
      throw markLoadFailure(error);
    });
}

export function lazyAdminPanel<P>(load: () => Promise<{ default: ComponentType<P> }>) {
  return lazy(markImportFailure(load));
}
