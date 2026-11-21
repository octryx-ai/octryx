import { formatDateTime, formatExactTime } from "../../utils/dateTime";
import type { ImageReport } from "./pluginsApi";
import { imageReportView } from "./pluginsModel";

// Admin › Plugins, "From the image" (plugins contract §5/§6): what the last start of Octryx did with the image's
// plugin folder. Platform admins only; without the report (403 or not loaded) the section is not shown.
export function PluginImageReport({ report }: { report: ImageReport | null }) {
  if (!report) return null;
  const view = imageReportView(report);

  return (
    <section className="plg-section" data-testid="plugins-image">
      <div className="plg-section__head">
        <h2 className="plg-section__title">From the image</h2>
        <p className="plg-muted">Octryx reads the image&apos;s plugin folder at every start. What is there becomes available to every Workspace.</p>
      </div>
      <dl className="plg-facts">
        <dt>Folder</dt><dd><code className="plg-mono">{view.folder}</code></dd>
        <dt>Last start</dt>
        <dd>{view.started ? <span title={formatExactTime(view.started)}>{formatDateTime(view.started)}</span> : "Not read since this server started"}</dd>
        {view.emptyText ? null : (<><dt>Result</dt><dd data-testid="plugins-image-counts">{view.counts}</dd></>)}
      </dl>
      {view.emptyText && view.started ? <p className="plg-muted" data-testid="plugins-image-empty">{view.emptyText}</p> : null}
      {view.failed.length ? (
        <ul className="plg-list" data-testid="plugins-image-failed">
          {view.failed.map((item) => (
            <li key={item.key} className="plg-item plg-item--problem">
              <span className="plg-item__line">
                <span className="plg-item__name">{item.title}</span>
                {item.detail ? <code className="plg-mono plg-muted">{item.detail}</code> : null}
              </span>
              <span className="plg-item__reason">{item.reason}</span>
              {item.message ? <span className="plg-item__meta">{item.message}</span> : null}
              {item.items.length ? (
                <ul className="plg-sublist">
                  {item.items.map((text, index) => <li key={index} className="plg-item__meta">{text}</li>)}
                </ul>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
