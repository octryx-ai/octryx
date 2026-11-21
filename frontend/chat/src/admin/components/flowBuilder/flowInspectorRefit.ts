import { useEffect, useRef } from "react";

// Opening or closing the step inspector changes the graph's space (it is a column beside the graph,
// or a panel below it on a narrow editor). Refit once per open/close: never on mount, re-renders or
// switching between selected steps, and never for the workflow definition itself.
export function useRefitOnInspectorToggle(open: boolean, refit: () => void): void {
  const wasOpen = useRef(open);
  const refitRef = useRef(refit);
  useEffect(() => {
    refitRef.current = refit;
  }, [refit]);
  useEffect(() => {
    if (wasOpen.current === open) return;
    wasOpen.current = open;
    refitRef.current();
  }, [open]);
}
