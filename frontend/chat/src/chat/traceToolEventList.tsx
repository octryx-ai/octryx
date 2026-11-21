// The tool events of a turn: compact bursts grouped per tool, or one full card per event.

import type { ToolArtifact, ToolEvent } from "../chatThreadTypes";
import { groupToolEvents } from "./traceUiHelpers";
import { visibleToolEvents } from "./traceToolEventValues";
import { ToolBurst } from "./ToolBurst";
import { ToolEventCard } from "./ToolEventCard";

export function ToolEventList({
  events,
  compact = false,
  onRetryFromToolEvent,
  onPreviewArtifact,
  actionsDisabled = false,
}: {
  events: ToolEvent[];
  compact?: boolean;
  onRetryFromToolEvent?: (event: ToolEvent) => void | Promise<void>;
  onPreviewArtifact?: (artifact: ToolArtifact) => void;
  actionsDisabled?: boolean;
}) {
  const displayEvents = visibleToolEvents(events);
  if (!displayEvents.length) {
    return null;
  }

  if (compact) {
    const groups = groupToolEvents(displayEvents);
    return (
      <div className="tool-list tool-list--compact tool-list--grouped">
        {groups.map((group) => (
          <ToolBurst key={group.key + group.events[0].id} group={group} onRetryFromToolEvent={onRetryFromToolEvent}
            onPreviewArtifact={onPreviewArtifact} actionsDisabled={actionsDisabled} />
        ))}
      </div>
    );
  }

  return (
    <div className="tool-list">
      {displayEvents.map((event) => (
        <ToolEventCard key={event.id} event={event} onRetryFromToolEvent={onRetryFromToolEvent}
          onPreviewArtifact={onPreviewArtifact} actionsDisabled={actionsDisabled} />
      ))}
    </div>
  );
}
