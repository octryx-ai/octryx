import type { ReactNode } from "react";

import { StatusLabel } from "../../../layout/StatusLabel";
import { roleBadges, TRUSTED_BADGE, type ErrorView } from "./workRolesModel";

// Small shared pieces of the work-role pages.

export function RoleBadges({ role }: { role: { built_in: boolean; trusted: boolean; is_active: boolean } }) {
  return (
    <span className="wr-badges">
      {roleBadges(role).map((badge) => <StatusLabel key={badge.label} label={badge.label} tone={badge.tone} title={badge.title} />)}
    </span>
  );
}

/** A role as a chip; a trusted role carries its badge in the attention tone. */
export function RoleChip({ name, trusted, onRemove, removeLabel }: {
  name: string;
  trusted: boolean;
  onRemove?: () => void;
  removeLabel?: string;
}) {
  return (
    <span className={`wr-chip${trusted ? " wr-chip--trusted" : ""}`} title={trusted ? TRUSTED_BADGE : undefined}>
      <span>{name}</span>
      {trusted ? <span className="wr-chip__note">· {TRUSTED_BADGE}</span> : null}
      {onRemove ? (
        <button type="button" className="wr-chip__remove" aria-label={removeLabel ?? `Remove ${name}`} onClick={onRemove}>×</button>
      ) : null}
    </span>
  );
}

/** A failed call: the API's message, then `setting` / `who_can_change` verbatim when present. */
export function ErrorLine({ error }: { error: ErrorView | null }) {
  if (!error) return null;
  return (
    <div className={`wr-error${error.conflict ? " wr-error--info" : ""}`} role={error.conflict ? "status" : "alert"} data-testid="work-roles-error">
      <p>{error.message}</p>
      {error.setting ? <p className="wr-error__meta">Setting: {error.setting}</p> : null}
      {error.whoCanChange ? <p className="wr-error__meta">Who can change it: {error.whoCanChange}</p> : null}
    </div>
  );
}

export function Card({ title, meta, actions, children, testId }: {
  title: string;
  meta?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
  testId?: string;
}) {
  return (
    <section className="ds-card wr-card" aria-label={title} data-testid={testId}>
      <header className="wr-card__head">
        <div className="wr-card__copy">
          <h2 className="ds-card__title">{title}</h2>
          {meta ? <p className="ds-card__meta wr-card__meta">{meta}</p> : null}
        </div>
        {actions ? <div className="wr-card__actions">{actions}</div> : null}
      </header>
      {children}
    </section>
  );
}

export function CheckRow({ checked, disabled, onChange, title, sub, testId }: {
  checked: boolean;
  disabled?: boolean;
  onChange: (next: boolean) => void;
  title: ReactNode;
  sub?: ReactNode;
  testId?: string;
}) {
  return (
    <label className={`wr-check${disabled ? " is-disabled" : ""}`} data-testid={testId}>
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(event) => onChange(event.target.checked)} />
      <span className="wr-check__text">
        <span className="wr-check__title">{title}</span>
        {sub ? <span className="wr-check__sub">{sub}</span> : null}
      </span>
    </label>
  );
}
