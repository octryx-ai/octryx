import { PageHeader } from "../../layout/PageHeader";
import { PluginFrame } from "../../admin/components/plugins/PluginFrame";
import { type PluginViewer } from "../../admin/components/plugins/usePluginFrame";
import { desktopFetch } from "../../admin/components/plugins/pluginUiApi";
import type { PluginSlotEntry } from "../../admin/components/plugins/pluginUiModel";

// A plugin's page in the Work area (plugins contract §4): the area's page header with the plugin's name as the group,
// the plugin's own page in its sandboxed frame below.
export function WorkPluginPage({ entry, workspaceId, viewer }: { entry: PluginSlotEntry; workspaceId: string | null; viewer?: PluginViewer }) {
  return (
    <section className="work-area__main" data-testid="work-plugin-page">
      <PageHeader eyebrow={`Work · ${entry.pluginName}`} title={entry.slot.title} />
      <div className="work-area__body">
        <PluginFrame key={entry.key} install={{ id: entry.installId, name: entry.pluginName, scope: entry.scope }}
          slot={entry.slot} title={entry.slot.title} workspaceId={workspaceId} fetcher={desktopFetch}
          viewer={viewer ?? { id: "", name: "", role: "member" }} />
      </div>
    </section>
  );
}
