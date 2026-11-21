// More › a plugin's phone page (plugins contract §4 `phone` slots): the plugin's own page in the sandboxed frame, run
// as the person in the chosen Workspace. The frame, the bridge and the confirmation are the desktop's (PluginFrame);
// the phone passes its own request function, which renews the phone session.

import type { ReactNode } from "react";
import { PluginFrame } from "../admin/components/plugins/PluginFrame";
import { type PluginViewer } from "../admin/components/plugins/usePluginFrame";
import type { Fetcher } from "../admin/components/plugins/pluginUiApi";
import type { PluginSlotEntry } from "../admin/components/plugins/pluginUiModel";
import { api } from "./mobileSession";
import { DetailHeader } from "./PageHeader";

const phoneFetch: Fetcher = (path, init) => api(path, init);

export function PluginPage({ entry, workspaceId, workspaceName, viewer, switcher, onBack }: {
  entry: PluginSlotEntry;
  workspaceId: string;
  workspaceName: string;
  viewer: PluginViewer;
  switcher?: ReactNode;
  onBack: () => void;
}) {
  return (
    <div className="m-screen">
      <DetailHeader title={entry.slot.title} subtitle={[entry.pluginName, workspaceName].filter(Boolean).join(" · ")} onBack={onBack} />
      <main className="m-body" data-testid="m-plugin-page">
        {switcher}
        <PluginFrame key={`${entry.key}:${workspaceId}`} install={{ id: entry.installId, name: entry.pluginName, scope: entry.scope }}
          slot={entry.slot} title={entry.slot.title} workspaceId={workspaceId || null} viewer={viewer} fetcher={phoneFetch} compact />
      </main>
    </div>
  );
}

export { phoneFetch };
