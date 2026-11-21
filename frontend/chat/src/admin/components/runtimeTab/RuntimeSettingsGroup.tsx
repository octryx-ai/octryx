import type { ReactNode } from "react";
import "./runtimeSections.css";

type RuntimeSettingsGroupProps = {
  title: string;
  /** One line: what this group decides. Shown as the header's tooltip; the page help explains it. */
  purpose: string;
  children: ReactNode;
};

// A labelled group of runtime settings: section header and fields; no explanatory line on the page.
export function RuntimeSettingsGroup({ title, purpose, children }: RuntimeSettingsGroupProps) {
  return (
    <section className="runtime-group">
      <div className="admin-panel__section-header runtime-group__header" title={purpose}>
        <span>{title}</span>
      </div>
      {children}
    </section>
  );
}

type RuntimeFieldProps = {
  id: string;
  label: string;
  help?: string;
  wide?: boolean;
  children: ReactNode;
};

// One labelled field with optional help text below it (design guide 9.2).
export function RuntimeField({ id, label, help, wide, children }: RuntimeFieldProps) {
  return (
    <div className={`admin-form-field${wide ? " admin-form-grid__full" : ""}`}>
      <label className="admin-form-field__label" htmlFor={id}>
        {label}
      </label>
      {children}
      {help ? <span className="admin-form-help">{help}</span> : null}
    </div>
  );
}
