// The two headers of the phone: a tab's page (large title, the Workspace switch, a few actions) and a detail page
// (back, title and subtitle, actions). Both stay at the top under the status bar.

import type { ReactNode } from "react";
import { Icon } from "./icons";

export function TabHeader({
  title,
  subtitle,
  switcher,
  actions,
}: {
  title: string;
  subtitle?: ReactNode;
  switcher?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="m-top m-top-tab">
      <div className="m-top-row">
        <h1 className="m-page-title">{title}</h1>
        {actions && <div className="m-top-actions">{actions}</div>}
      </div>
      {(switcher || subtitle) && (
        <div className="m-top-meta">
          {switcher}
          {subtitle && <span className="m-top-subtitle">{subtitle}</span>}
        </div>
      )}
    </header>
  );
}

export function DetailHeader({
  title,
  subtitle,
  onBack,
  backLabel = "Back",
  actions,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  onBack: () => void;
  backLabel?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="m-top">
      <button type="button" className="m-icon-button m-back" aria-label={backLabel} onClick={onBack}>
        <Icon name="back" />
      </button>
      <div className="m-top-text">
        <strong>{title}</strong>
        {subtitle && <span className="m-muted">{subtitle}</span>}
      </div>
      {actions}
    </header>
  );
}
