import { useEffect, useRef } from "react";

import type { ToolArtifact, ToolEvent } from "../chatThreadTypes";
import { ToolEventList } from "./traceToolEventList";
import { TraceTurnDiffSection } from "./traceTurnDiffUi";
import { TraceWorkflowChecksPanel } from "./traceWorkflowChecksPanel";
import { TraceWorkflowRoutingPanel } from "./traceWorkflowRoutingPanel";

// Escape closes the trace like the side panels (SidePanel.ts): the listener is on the document, so it
// works right after opening and after a click inside. Focus moves into the drawer and back to the opener on close.
function useDrawerEscape(open: boolean, onClose: () => void) {
  const drawerRef = useRef<HTMLElement | null>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    if (!open || typeof document === "undefined") return undefined;
    const opener = document.activeElement as HTMLElement | null;
    drawerRef.current?.focus?.();
    const onKey = (event: KeyboardEvent) => {
      // A dialog laid over the trace (the turn trace modal, a confirmation) closes first, on its own Escape.
      const over = document.querySelector?.('.admin-modal[role="dialog"], [role="alertdialog"]');
      if (event.key === "Escape" && !event.defaultPrevented && !over) {
        event.preventDefault();
        closeRef.current();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      opener?.focus?.();
    };
  }, [open]);
  return drawerRef;
}

function TurnDiffSection({ turnDiff }: { turnDiff?: Record<string, unknown> | null }) {
  return (
    <section className="trace-drawer__section trace-drawer__section--diff">
      <div className="trace-drawer__section-header">
        <div className="trace-drawer__section-title">
          Execution diff
        </div>
        <div className="trace-drawer__section-copy">
          Commands, file changes, and policy events from the last run.
        </div>
      </div>
      <TraceTurnDiffSection
        turnDiff={turnDiff}
        keyPrefix="trace-drawer"
      />
    </section>
  );
}

function ToolEventsSection({ events, onRetryFromToolEvent, onPreviewArtifact, actionsDisabled }: {
  events: ToolEvent[];
  onRetryFromToolEvent?: (event: ToolEvent) => void | Promise<void>;
  onPreviewArtifact?: (artifact: ToolArtifact) => void;
  actionsDisabled: boolean;
}) {
  return (
    <section className="trace-drawer__section">
      <div className="trace-drawer__section-header">
        <div className="trace-drawer__section-title">Tool events</div>
        <div className="trace-drawer__section-copy">
          Retry from a call or preview any attached artifact.
        </div>
      </div>
      {events.length ? (
        <ToolEventList
          events={events}
          compact
          onRetryFromToolEvent={onRetryFromToolEvent}
          onPreviewArtifact={onPreviewArtifact}
          actionsDisabled={actionsDisabled}
        />
      ) : (
        <div className="trace-empty">
          No tool calls yet for this chat.
        </div>
      )}
    </section>
  );
}

function DrawerHeader({ onClose }: { onClose: () => void }) {
  return (
    <div className="trace-drawer__header">
      <div className="trace-drawer__heading">
        <div className="trace-drawer__eyebrow">Last execution changes</div>
        <h3 className="trace-drawer__title">Execution trace</h3>
      </div>
      <button
        type="button"
        className="admin-panel__icon-btn"
        onClick={onClose}
        aria-label="Close execution trace"
      >
        <span aria-hidden="true">×</span>
      </button>
    </div>
  );
}

type TraceDrawerProps = {
  open: boolean;
  events: ToolEvent[];
  sessionId?: string | null;
  turnDiff?: Record<string, unknown> | null;
  routingResolution?: Record<string, unknown> | null;
  workflowContract?: Record<string, unknown> | null;
  onClose: () => void;
  onRetryFromToolEvent?: (event: ToolEvent) => void | Promise<void>;
  onPreviewArtifact?: (artifact: ToolArtifact) => void;
  actionsDisabled?: boolean;
  // Admins also see the workflow check results of this session.
  canInspectSetup?: boolean;
};

export function TraceDrawer({
  open,
  events,
  sessionId,
  turnDiff,
  routingResolution,
  workflowContract,
  onClose,
  onRetryFromToolEvent,
  onPreviewArtifact,
  actionsDisabled = false,
  canInspectSetup = false,
}: TraceDrawerProps) {
  const hasTurnDiff = Boolean(turnDiff);
  const drawerRef = useDrawerEscape(open, onClose);
  return (
    <>
      <div
        className={`trace-backdrop ${open ? "trace-backdrop--visible" : ""}`}
        onClick={onClose}
      />
      <aside
        ref={drawerRef}
        tabIndex={-1}
        className={`trace-drawer ${open ? "trace-drawer--open" : ""}`}
        role={open ? "dialog" : undefined}
        aria-modal={open ? "true" : undefined}
        aria-hidden={!open}
        aria-label="Execution trace"
      >
        <DrawerHeader onClose={onClose} />
        <div className="trace-drawer__body">
          {hasTurnDiff ? <TurnDiffSection turnDiff={turnDiff} /> : null}
          <TraceWorkflowRoutingPanel
            resolution={routingResolution}
            workflowContract={workflowContract}
          />
          {canInspectSetup ? <TraceWorkflowChecksPanel sessionId={sessionId} open={open} /> : null}
          <ToolEventsSection events={events} onRetryFromToolEvent={onRetryFromToolEvent}
            onPreviewArtifact={onPreviewArtifact} actionsDisabled={actionsDisabled} />
        </div>
      </aside>
    </>
  );
}
