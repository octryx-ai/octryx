import { useEffect, useRef, type RefObject } from "react";
import { createPortal } from "react-dom";

import { PinIcon } from "./ChatShellIcons";
import { ThreadMarker } from "./ThreadRowParts";
import { THREAD_MARKERS } from "./threadSignalKind";
import { LaptopIcon } from "./threadSidebarIcons";

/** The ⓘ popover: what every row marker means (generated from THREAD_MARKERS). */
export function ThreadMarkerLegend({
  anchorRef,
  onClose,
}: {
  anchorRef: RefObject<HTMLElement | null>;
  onClose: () => void;
}) {
  const popoverRef = useRef<HTMLDivElement>(null);
  const anchor = anchorRef.current?.getBoundingClientRect();

  useEffect(() => {
    const onPointer = (event: MouseEvent) => {
      const target = event.target as Node;
      if (!popoverRef.current?.contains(target) && !anchorRef.current?.contains(target)) {
        onClose();
      }
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
        anchorRef.current?.focus();
      }
    };
    window.addEventListener("mousedown", onPointer);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onPointer);
      window.removeEventListener("keydown", onKey);
    };
  }, [anchorRef, onClose]);

  return createPortal(
    <div
      ref={popoverRef}
      className="thread-legend"
      role="dialog"
      aria-label="Row markers"
      style={anchor ? { top: anchor.bottom + 6, left: Math.max(8, anchor.left - 8) } : undefined}
    >
      <h3>Row markers</h3>
      <ul>
        {THREAD_MARKERS.map((marker) => (
          <li key={marker.kind}>
            <ThreadMarker kind={marker.kind} />
            <span>
              {marker.label}
              <small>{marker.hint}</small>
            </span>
          </li>
        ))}
        <li>
          <ThreadMarker kind="done" />
          <span>
            No marker
            <small>Finished — nothing to do.</small>
          </span>
        </li>
        <li>
          <span className="thread-card__device thread-card__device--icon" aria-hidden="true">
            <LaptopIcon />
          </span>
          <span>
            Device run
            <small>Runs on one of your devices (Run on).</small>
          </span>
        </li>
        <li>
          <span className="thread-card__pin" aria-hidden="true">
            <PinIcon />
          </span>
          <span>Pinned</span>
        </li>
      </ul>
    </div>,
    document.body,
  );
}
