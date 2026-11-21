import { useCallback, useEffect, useState } from "react";

import { EmptyLine } from "../../../layout/EmptyLine";
import { SidePanel } from "../../../layout/SidePanel";
import { AvailablePluginList, type RowState } from "./AvailablePluginList";
import {
  listAvailable, loadImageReport, switchPlugin,
  type AvailablePlugin, type AvailableViewer, type ImageReport,
} from "./pluginsApi";
import { afterSwitch, emptyText, pluginErrorView } from "./pluginsModel";
import { PluginDetailPanel } from "./PluginDetailPanel";
import { PluginImageReport } from "./PluginImageReport";
import { PluginSettingsForm } from "./PluginSettingsForm";
import "./plugins.css";

type Workspace = { id: string; name: string };

export type PluginsPageProps =
  // Workspace › Plugins: the image's plugins with their switch; its admins and owners switch.
  | { mode: "workspace"; workspace: Workspace; isPlatformAdmin: boolean }
  // Admin › Plugins: the image's plugins with the Workspaces they are in, and what the last start did.
  | { mode: "platform"; workspaces: Workspace[]; isPlatformAdmin: boolean };

// The image report: platform admins only; anyone else gets null (403) and the page does without it.
function useImageReport(enabled: boolean): ImageReport | null {
  const [report, setReport] = useState<ImageReport | null>(null);
  useEffect(() => {
    if (!enabled) return;
    let live = true;
    loadImageReport().then((value) => { if (live) setReport(value); }, () => { if (live) setReport(null); });
    return () => { live = false; };
  }, [enabled]);
  return report;
}

// The page's state: the image's plugins, the rows being switched, the open plugin
// and the one whose settings are asked for, and the optimistic switch.
function usePluginsPage(workspaceId: string | null, isPlatformAdmin: boolean) {
  const [plugins, setPlugins] = useState<AvailablePlugin[] | null>(null);
  const [viewer, setViewer] = useState<AvailableViewer | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [states, setStates] = useState<Record<string, RowState>>({});
  const [open, setOpen] = useState<string | null>(null);
  const [settingsFor, setSettingsFor] = useState<AvailablePlugin | null>(null);
  const report = useImageReport(isPlatformAdmin);

  const load = useCallback(async () => {
    try {
      const available = await listAvailable(workspaceId);
      setPlugins(available.plugins);
      setViewer(available.viewer);
      setError(null);
    } catch (failure) {
      setPlugins([]);
      setError(pluginErrorView(failure).text);
    }
  }, [workspaceId]);
  useEffect(() => { void load(); }, [load]);

  const setState = (key: string, state: RowState) => setStates((current) => ({ ...current, [key]: state }));
  const replace = (next: AvailablePlugin) => setPlugins((current) => (current ?? []).map((item) => (item.plugin === next.plugin ? next : item)));

  // Optimistic: the row moves at once and stays busy; a refusal puts it back and says why on the row.
  const toggle = async (item: AvailablePlugin) => {
    if (!workspaceId || states[item.plugin]?.busy) return;
    const on = !item.active;
    replace({ ...item, active: on });
    setState(item.plugin, { busy: true, error: null });
    try {
      const install = await switchPlugin(item.plugin, workspaceId, on);
      const next = afterSwitch(item, install);
      replace(next);
      setState(item.plugin, {});
      if (on && next.active && next.needs_settings) setSettingsFor(next);
    } catch (failure) {
      replace(item);
      setState(item.plugin, { error: pluginErrorView(failure).text });
    }
  };

  return { plugins, viewer, error, states, open, setOpen, settingsFor, setSettingsFor, report, load, toggle };
}

// Plugins come only from the image's plugin folder (plugins contract §6): one list of them; in a
// Workspace an admin switches each on or off, in Admin › Plugins a platform admin sees where they are and what the
// last start did with the folder.
export function PluginsPage(props: PluginsPageProps) {
  const workspaceId = props.mode === "workspace" ? props.workspace.id : null;
  const {
    plugins, viewer, error, states, open, setOpen, settingsFor, setSettingsFor, report, load, toggle,
  } = usePluginsPage(workspaceId, props.isPlatformAdmin);
  const closeSettings = () => { setSettingsFor(null); void load(); };
  const folder = report?.folder ?? null;
  const intro = props.mode === "workspace"
    ? "Plugins come with the Octryx image. Switching one on brings its skills, workflows, roles and pages into this Workspace; switching it off keeps everything for later."
    : "Plugins come with the Octryx image. A Workspace admin switches each on where it is needed.";

  return (
    <div className="plg-page" data-testid={`plugins-${props.mode}`}>
      <p className="plg-muted plg-intro">{intro}</p>
      {error ? <p className="plg-error" role="alert">{error}</p> : null}
      {plugins === null ? <p className="plg-muted">Loading plugins…</p> : plugins.length ? (
        <AvailablePluginList plugins={plugins} viewer={viewer} states={states} workspaces={props.mode === "platform"}
          onToggle={(item) => void toggle(item)} onOpen={(item) => setOpen(item.install_id)} onSettings={setSettingsFor} />
      ) : error ? null : <EmptyLine text={emptyText(folder)} testId="plugins-empty" />}
      {props.mode === "platform" && props.isPlatformAdmin ? <PluginImageReport report={report} /> : null}
      {open ? (
        <PluginDetailPanel installId={open} canEdit={Boolean(viewer?.can_activate)} onClose={() => { setOpen(null); void load(); }} />
      ) : null}
      {settingsFor?.install_id ? (
        <PluginSettingsPanel name={settingsFor.name} installId={settingsFor.install_id} canEdit={Boolean(viewer?.can_activate)}
          onClose={closeSettings} />
      ) : null}
    </div>
  );
}

// The settings of a plugin just switched on, needed before it can work.
function PluginSettingsPanel({ name, installId, canEdit, onClose }: {
  name: string; installId: string; canEdit: boolean; onClose: () => void;
}) {
  return (
    <SidePanel title={`Settings for ${name}`} subtitle="Needed before the plugin can work" onClose={onClose}
      size="narrow" testId="plugin-settings-panel"
      footer={<button type="button" className="ds-btn" onClick={onClose}>Done</button>}>
      <div className="plg-stack">
        <p className="plg-muted">{name} is on. Fill in its settings and save them; until then the list shows “Needs settings”.</p>
        <PluginSettingsForm installId={installId} canEdit={canEdit} />
      </div>
    </SidePanel>
  );
}
