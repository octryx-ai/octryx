import { useEffect, useState } from "react";

import type { PluginInstall } from "./pluginsApi";
import type { Fetcher } from "./pluginUiApi";
import { collectSlots, type PluginSlotEntry } from "./pluginUiModel";

export type PluginSlotState = { entries: PluginSlotEntry[]; installs: PluginInstall[] };

const EMPTY: PluginSlotState = { entries: [], installs: [] };

/** A frame asks for its own /ui only when it opens; a refusal means no slots. */
export function usePluginSlots(workspaceId: string | null, fetcher: Fetcher, reloadKey: unknown = 0): PluginSlotState {
  const [state, setState] = useState<PluginSlotState>(EMPTY);
  useEffect(() => {
    if (!workspaceId) { setState(EMPTY); return; }
    let live = true;
    fetcher<{ plugins?: PluginInstall[] }>(`/api/v1/plugins?workspace_id=${encodeURIComponent(workspaceId)}`).then(
      (list) => { if (live) setState({ entries: collectSlots(list.plugins ?? []), installs: list.plugins ?? [] }); },
      () => { if (live) setState(EMPTY); },
    );
    return () => { live = false; };
  }, [workspaceId, fetcher, reloadKey]);
  return state;
}
