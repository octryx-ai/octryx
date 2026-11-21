import { CodingNavIcon, type CodingNavKey } from "../coding/CodingAreaNav";
import { WorkNavIcon } from "./WorkAreaViews";
import { WORK_AREA_ENTRIES, type WorkAreaEntry, type WorkAreaHost } from "./workAreaMenu";
import type { WorkNavKey } from "./workTypes";
import type { PluginSlotEntry } from "../../admin/components/plugins/pluginUiModel";
import { visibleToReader } from "./workAccess";

export type WorkPluginGroup = { pluginName: string; installId: string; pages: PluginSlotEntry[] };

// A plugin's page (plugins contract §4): one glyph for all of them, the plugin's name is the group above.
function PluginPageIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M4 4h12v12H4z" />
      <path d="M4 8h12" />
    </svg>
  );
}

// The one menu of the Work area (Work and Coding pages, workAreaMenu.ts). An entry of the same host switches the
// page in place; an entry of the other host opens it there (`onOpenOther`). Pages of installed plugins follow, one
// group per plugin under its name (`plugins`); they open in the Work host.
export function WorkAreaNav({ host, activeKey, onSelectLocal, onOpenOther, plugins = [], activePlugin = null, onOpenPlugin,
  canManage = true }: {
  host: WorkAreaHost;
  activeKey: string;
  onSelectLocal: (key: string) => void;
  onOpenOther: (entry: WorkAreaEntry) => void;
  plugins?: WorkPluginGroup[];
  activePlugin?: string | null;
  onOpenPlugin?: (key: string) => void;
  /** False for a Workspace member without the Work role: the pages that configure or start work are not shown. */
  canManage?: boolean;
}) {
  let currentGroup = "";
  return (
    <nav className="work-area__nav" aria-label="Work navigation">
      {WORK_AREA_ENTRIES.filter((entry) => canManage || visibleToReader(entry.host, entry.key)).map((entry) => {
        const showGroup = entry.group !== currentGroup;
        currentGroup = entry.group;
        const active = !activePlugin && entry.host === host && entry.key === activeKey;
        return (
          <div key={`${entry.host}:${entry.key}`} className="work-area__nav-row">
            {showGroup ? <div className="work-area__nav-section">{entry.group}</div> : null}
            <button type="button" className={`work-area__nav-button ${active ? "is-active" : ""}`}
              aria-current={active ? "page" : undefined} title={entry.label} data-entry={`${entry.host}:${entry.key}`}
              onClick={() => (entry.host === host ? onSelectLocal(entry.key) : onOpenOther(entry))}>
              {entry.host === "work" ? <WorkNavIcon navKey={entry.key as WorkNavKey} /> : <CodingNavIcon navKey={entry.key as CodingNavKey} />}
              <span>{entry.label}</span>
            </button>
          </div>
        );
      })}
      {plugins.map((group) => (
        <div key={group.installId} className="work-area__nav-row" data-testid="work-nav-plugin">
          <div className="work-area__nav-section">{group.pluginName}</div>
          {group.pages.map((page) => {
            const active = page.key === activePlugin;
            return (
              <button key={page.key} type="button" className={`work-area__nav-button ${active ? "is-active" : ""}`}
                aria-current={active ? "page" : undefined} title={page.slot.title} data-entry={`plugin:${page.key}`}
                onClick={() => onOpenPlugin?.(page.key)}>
                <PluginPageIcon />
                <span>{page.slot.title}</span>
              </button>
            );
          })}
        </div>
      ))}
    </nav>
  );
}
