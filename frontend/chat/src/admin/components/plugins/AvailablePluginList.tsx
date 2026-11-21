import { StatusLabel } from "../../../layout/StatusLabel";
import type { AvailablePlugin, AvailableViewer } from "./pluginsApi";
import { activeWorkspacesText, availableRow } from "./pluginsModel";
import { PluginSwitch } from "./PluginSwitch";

export type RowState = { busy?: boolean; error?: string | null };

// The image's plugins as one list (plugins contract §6): name, version, publisher, description and what it brings in
// plain lines. In a Workspace each row has its switch (or On / Off as text for members); in Admin › Plugins it says
// in how many Workspaces the plugin is on instead. A plugin missing from the image is greyed, without a switch.
export function AvailablePluginList({ plugins, viewer, states = {}, workspaces = false, onToggle, onOpen, onSettings }: {
  plugins: AvailablePlugin[];
  viewer: AvailableViewer | null;
  states?: Record<string, RowState>;
  // Admin › Plugins: the Workspaces it is on in, no switch.
  workspaces?: boolean;
  onToggle?: (item: AvailablePlugin) => void;
  onOpen?: (item: AvailablePlugin) => void;
  onSettings?: (item: AvailablePlugin) => void;
}) {
  return (
    <ul className="plg-avail" data-testid="plugins-available">
      {plugins.map((item) => {
        const row = availableRow(item, workspaces ? null : viewer);
        const state = states[item.plugin] ?? {};
        const count = workspaces ? activeWorkspacesText(item.active_workspaces) : "";
        return (
          <li key={row.key} className={`plg-avail__row${row.missing ? " is-missing" : ""}`} data-testid="plugin-row" data-plugin={row.key}>
            <div className="plg-avail__main">
              <div className="plg-avail__head">
                {row.canOpen && onOpen ? (
                  <button type="button" className="plg-avail__name ds-link-button" onClick={() => onOpen(item)} data-testid="plugin-open">{row.name}</button>
                ) : <span className="plg-avail__name">{row.name}</span>}
                <span className="plg-muted">{row.meta}</span>
                {row.missing ? <StatusLabel label="Missing from the image" tone="neutral" testId="plugin-missing" /> : null}
                {row.needsSettings ? (
                  onSettings && row.switchable ? (
                    <button type="button" className="plg-avail__flag" onClick={() => onSettings(item)} data-testid="plugin-needs-settings">
                      <StatusLabel label="Needs settings" tone="attention" />
                    </button>
                  ) : <StatusLabel label="Needs settings" tone="attention" testId="plugin-needs-settings" />
                ) : null}
              </div>
              {row.description ? <p className="plg-avail__text">{row.description}</p> : null}
              {row.lines.length ? (
                <ul className="plg-avail__lines">{row.lines.map((line, index) => <li key={index}>{line}</li>)}</ul>
              ) : null}
              {state.error ? <p className="plg-avail__error" role="alert" data-testid="plugin-row-error">{state.error}</p> : null}
            </div>
            <div className="plg-avail__side">
              {workspaces ? (
                count ? <span className="plg-muted" data-testid="plugin-workspaces">{count}</span> : null
              ) : row.missing ? null : (
                <PluginSwitch on={row.on} label={row.name} busy={Boolean(state.busy)} editable={row.switchable}
                  onToggle={() => onToggle?.(item)} testId="plugin-switch" />
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
