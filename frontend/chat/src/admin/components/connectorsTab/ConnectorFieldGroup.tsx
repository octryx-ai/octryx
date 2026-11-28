import type { ReactNode } from "react";
import "./connectorCardGroups.css";

export function ConnectorFieldGroup({ group, title, children }: { group: string; title: string; children: ReactNode }) {
  return (
    <fieldset className="ds-form-section connector-card__group" data-group={group}>
      <legend className="ds-form-section__title">{title}</legend>
      <div className="ds-form-section__body">{children}</div>
    </fieldset>
  );
}
