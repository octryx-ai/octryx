import { useEffect, useRef } from "react";

import type { ThreadSummary } from "../chatThreadTypes";
import { PinIcon } from "./ChatShellIcons";
import { threadMarkerKind, threadSignalLabel } from "./threadSignalKind";
import { LaptopIcon } from "./threadSidebarIcons";

/** A row marker: shape plus colour plus a text label; nothing at all for done/stopped. */
export function ThreadMarker({ kind, stopReason }: { kind: string; stopReason?: string | null }) {
  const marker = threadMarkerKind(kind);
  if (!marker) {
    return <span className="thread-card__status thread-card__status--none" aria-hidden="true" />;
  }
  return (
    <span
      className={`thread-card__status thread-card__status--${marker}`}
      role="img"
      aria-label={threadSignalLabel(marker, stopReason) ?? undefined}
    />
  );
}

/** The device a thread runs on: icon-only in the row, named in the hover card. */
export function ThreadDeviceBadge({ deviceName, full = false }: { deviceName: string; full?: boolean }) {
  if (full) {
    return (
      <span className="thread-card__device">
        <LaptopIcon />
        <span>{deviceName}</span>
      </span>
    );
  }
  return (
    <span
      className="thread-card__device thread-card__device--icon"
      role="img"
      aria-label={`Runs on device ${deviceName}`}
    >
      <LaptopIcon />
    </span>
  );
}

/** Pin, device and last-activity time after the title; the "…" trigger covers the time on hover. */
export function ThreadRowMeta({ thread, timeLabel }: { thread: ThreadSummary; timeLabel: string }) {
  return (
    <span className="thread-card__meta">
      {thread.isPinned ? (
        <span className="thread-card__pin" aria-label="Pinned" role="img">
          <PinIcon />
        </span>
      ) : null}
      {thread.executionTarget?.kind === "device" ? (
        <ThreadDeviceBadge deviceName={thread.executionTarget.deviceName} />
      ) : null}
      {timeLabel ? <span className="thread-card__time">{timeLabel}</span> : null}
    </span>
  );
}

/** Rename in place (F2 or the row menu): Enter or leaving the field saves, Esc cancels (null). */
export function ThreadRenameInput({ title, onDone }: { title: string; onDone: (title: string | null) => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const settled = useRef(false);

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  const finish = (value: string | null) => {
    if (settled.current) {
      return;
    }
    settled.current = true;
    onDone(value);
  };

  return (
    <input
      ref={inputRef}
      className="thread-card__rename"
      defaultValue={title}
      maxLength={120}
      aria-label="Chat title"
      onKeyDown={(event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          finish(event.currentTarget.value);
        } else if (event.key === "Escape") {
          event.preventDefault();
          event.stopPropagation();
          finish(null);
        }
      }}
      onBlur={(event) => finish(event.currentTarget.value)}
    />
  );
}
