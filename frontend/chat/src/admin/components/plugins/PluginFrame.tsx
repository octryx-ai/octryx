import type { PluginInstall, PluginUiSlot } from "./pluginsApi";
import { PluginConfirmDialog } from "./PluginConfirmDialog";
import type { Fetcher } from "./pluginUiApi";
import { frameSrc } from "./pluginUiModel";
import { pluginApprovalActions, usePluginBridge, usePluginFrameState } from "./usePluginFrame";
import type { PluginObject, PluginSlotKind, PluginViewer } from "./usePluginFrame";
import "./plugins.css";

// No allow-same-origin: the origin is opaque, so messages go out with "*" and carry nothing secret.
export function PluginFrame({ install, slot, slotKind, title, workspaceId, viewer, object = null, fetcher, compact = false }: {
  install: Pick<PluginInstall, "id" | "name" | "scope">;
  slot: PluginUiSlot;
  slotKind?: PluginSlotKind;
  title: string;
  workspaceId: string | null;
  viewer: PluginViewer;
  object?: PluginObject;
  fetcher: Fetcher;
  compact?: boolean;
}) {
  const kind: PluginSlotKind = slotKind ?? (compact ? "phone" : "page");
  const frame = usePluginFrameState(fetcher, install.id, { workspaceId, viewer, object, slot: { kind, id: slot.id } });
  const bridge = usePluginBridge(fetcher, install, frame);
  const { current, approve, decline } = pluginApprovalActions(fetcher, frame, bridge);
  const { frameRef, wrapRef, view, failure, height, deciding, decideError } = frame;

  if (failure) {
    return <p className="plg-frame-failed" title={failure.title || undefined} data-testid="plugin-frame-failed">{failure.text}</p>;
  }
  return (
    <div ref={wrapRef} className={`plg-frame${compact ? " plg-frame--compact" : ""}`} data-testid="plugin-frame">
      {view ? (
        <iframe ref={frameRef} key={view.base_url} className="plg-frame__iframe" title={title} src={frameSrc(view, slot)}
          sandbox="allow-scripts allow-forms" referrerPolicy="no-referrer" style={{ height }} />
      ) : (
        <p className="plg-muted plg-frame__loading">Loading {title}…</p>
      )}
      {current ? (
        <PluginConfirmDialog key={current.id} pluginName={install.name} approval={current.approval} fetcher={fetcher}
          busy={deciding} error={decideError} onApprove={() => void approve()} onDecline={() => void decline()} />
      ) : null}
    </div>
  );
}
