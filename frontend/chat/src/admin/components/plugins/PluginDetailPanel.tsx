import { useEffect, useState, type ReactNode } from "react";

import { SidePanel } from "../../../layout/SidePanel";
import { flowEditorHref } from "../../editorLinks";
import { loadPlugin, type PluginContribution, type PluginInstall, type PluginPermissions } from "./pluginsApi";
import { contributionName, kindLabel, pluginErrorView, uiContents } from "./pluginsModel";
import { installedText } from "./pluginWords";
import { PluginSettingsForm } from "./PluginSettingsForm";

function Block({ title, children, testId }: { title: string; children: ReactNode; testId?: string }) {
  return (
    <section className="plg-block" data-testid={testId}>
      <h3 className="plg-block__title">{title}</h3>
      {children}
    </section>
  );
}

function ContributionRow({ item, permissions }: { item: PluginContribution; permissions: PluginPermissions }) {
  const label = contributionName(item, permissions);
  const name = item.kind === "workflow" && !item.dropped ? <a href={flowEditorHref(item.id)}>{label}</a> : <span>{label}</span>;
  return (
    <li className={`plg-item plg-item--row${item.dropped ? " plg-item--dropped" : ""}`}
      data-testid={item.dropped ? "plugin-contribution-dropped" : undefined}>
      <span className="plg-item__kind">{kindLabel(item.kind)}</span>
      <span className="plg-item__name">{name}</span>
      {item.dropped ? <span className="plg-item__meta">No longer in this version</span> : null}
    </li>
  );
}

const hasSettings = (install: PluginInstall) => {
  const properties = (install.permissions.settings as { properties?: Record<string, unknown> } | null | undefined)?.properties;
  return Boolean(properties && Object.keys(properties).length);
};

// One plugin switched on in a Workspace: what it brought there, its pages and its settings (contract §4/§6). On and
// off is the switch in the list; who may switch edits the settings, everyone else reads them.
export function PluginDetailPanel({ installId, canEdit, onClose }: { installId: string; canEdit: boolean; onClose: () => void }) {
  const [install, setInstall] = useState<PluginInstall | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    loadPlugin(installId).then(
      (found) => { if (live) setInstall(found); },
      (failure) => { if (live) setError(pluginErrorView(failure).text); },
    );
    return () => { live = false; };
  }, [installId]);

  if (!install) {
    return (
      <SidePanel title="Plugin" onClose={onClose} testId="plugin-detail">
        {error ? <p className="plg-error" role="alert">{error}</p> : <p className="plg-muted">Loading…</p>}
      </SidePanel>
    );
  }
  // Current contributions first, the ones the current version dropped after them.
  const contributions = [...install.contributions].sort((a, b) => Number(Boolean(a.dropped)) - Number(Boolean(b.dropped)));
  const pages = uiContents(install.ui ?? install.permissions.ui);

  return (
    <SidePanel title={install.name} subtitle={`${install.version} · ${install.publisher}`} onClose={onClose} testId="plugin-detail">
      <div className="plg-stack">
        {install.description ? <p className="plg-detail__text">{install.description}</p> : null}
        <dl className="plg-facts">
          <dt>Switched on by</dt><dd>{installedText(install)}</dd>
          <dt>Plugin id</dt><dd><code className="plg-mono plg-muted">{install.plugin}</code></dd>
        </dl>
        <Block title="What it brought" testId="plugin-contributions">
          {contributions.length ? (
            <ul className="plg-list">{contributions.map((item) => <ContributionRow key={`${item.kind}-${item.id}`} item={item} permissions={install.permissions} />)}</ul>
          ) : <p className="plg-muted">Nothing.</p>}
        </Block>
        {pages.length ? (
          <Block title="Pages" testId="plugin-pages">
            <ul className="plg-list">
              {pages.map((page, index) => (
                <li key={`${page.where}-${index}`} className="plg-item plg-item--row">
                  <span className="plg-item__name">{page.title}</span>
                  <span className="plg-item__meta">{page.where}</span>
                </li>
              ))}
            </ul>
          </Block>
        ) : null}
        {hasSettings(install) ? (
          <Block title="Settings" testId="plugin-settings-block">
            <PluginSettingsForm installId={install.id} canEdit={canEdit} />
          </Block>
        ) : null}
      </div>
    </SidePanel>
  );
}
