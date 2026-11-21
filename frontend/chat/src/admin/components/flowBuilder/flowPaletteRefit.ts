// Refit the workflow graph once after the step palette opens or closes. The palette takes
// real space beside the graph, so a toggle changes the graph's width. React Flow learns the new
// size from its own resize observer, so the fit waits for the graph's next width change and then
// one animation frame; when the width does not change (for example a hidden palette on a small
// screen) a short fallback fits anyway. It fits only for a toggle: never for pans, selections,
// renders or window resizes, and it only moves the viewport, never the workflow definition.
// After dispose (the editor unmounts) nothing fits any more: a queued frame or fallback is
// cancelled, a late callback is ignored, and later calls do nothing.

export type PaletteRefitDeps = {
  fit: () => void;
  // Both schedulers return a function that cancels the scheduled callback.
  frame: (callback: () => void) => () => void;
  timer: (callback: () => void, ms: number) => () => void;
};

export const PALETTE_REFIT_FALLBACK_MS = 300;

export type PaletteRefit = {
  paletteToggled: () => void;
  graphResized: (width: number) => void;
  dispose: () => void;
};

export function createPaletteRefit({ fit, frame, timer }: PaletteRefitDeps): PaletteRefit {
  let pending = false;
  let disposed = false;
  let lastWidth: number | null = null;
  let cancelFallback: (() => void) | null = null;
  let cancelFrame: (() => void) | null = null;

  const flush = () => {
    if (!pending || disposed) return;
    pending = false;
    cancelFallback?.();
    cancelFallback = null;
    cancelFrame?.();
    cancelFrame = frame(() => {
      cancelFrame = null;
      if (!disposed) fit();
    });
  };

  return {
    paletteToggled() {
      if (disposed) return;
      pending = true;
      cancelFallback?.();
      cancelFallback = timer(flush, PALETTE_REFIT_FALLBACK_MS);
    },
    graphResized(width) {
      if (disposed) return;
      const changed = lastWidth !== null && Math.round(width) !== Math.round(lastWidth);
      lastWidth = width;
      if (changed) flush();
    },
    dispose() {
      disposed = true;
      pending = false;
      cancelFallback?.();
      cancelFallback = null;
      cancelFrame?.();
      cancelFrame = null;
    },
  };
}
