import { createPortal } from "react-dom";

import { ThreadDeviceBadge, ThreadMarker } from "./ThreadRowParts";
import { getThreadSignalKind, threadMarkerKind, threadSignalLabel } from "./threadSignalKind";
import { ThreadFolderIcon } from "./threadSidebarIcons";
import { threadTimeLabel } from "./threadTime";
import type { ThreadHoverState } from "./useThreadHoverCard";

export function ThreadHoverCard({ hover }: { hover: ThreadHoverState | null }) {
  if (!hover) {
    return null;
  }
  const { thread } = hover;
  const kind = getThreadSignalKind(thread);
  const marker = threadMarkerKind(kind);
  const time = threadTimeLabel(thread.lastActivityAt ?? thread.startedAt);
  return createPortal(
    <div className="thread-hovercard" role="tooltip" style={{ top: hover.top, left: hover.left }}>
      <strong>{thread.title}</strong>
      <div>
        <ThreadFolderIcon />
        <span>
          {hover.workspace}
          {time ? ` · ${time}` : ""}
        </span>
      </div>
      {marker ? (
        <div>
          <ThreadMarker kind={kind} stopReason={thread.latestTurnStopReason} />
          <span>{threadSignalLabel(kind, thread.latestTurnStopReason)}</span>
        </div>
      ) : null}
      {thread.executionTarget?.kind === "device" ? (
        <div>
          <ThreadDeviceBadge deviceName={`Run on: ${thread.executionTarget.deviceName}`} full />
        </div>
      ) : null}
    </div>,
    document.body,
  );
}
