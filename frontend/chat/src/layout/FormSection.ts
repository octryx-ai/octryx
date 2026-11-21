import { createElement, type ReactNode } from "react";

// Forms of the design system live only inside a side panel, in sections; expert fields sit under a collapsed
// "Advanced". Fields themselves keep the existing classes (admin-panel__field, admin-panel__input).

export type FormSectionProps = {
  title: string;
  children?: ReactNode;
  testId?: string;
};

export function FormSection({ title, children, testId }: FormSectionProps) {
  return createElement(
    "fieldset",
    { className: "ds-form-section", "data-testid": testId },
    createElement("legend", { className: "ds-form-section__title" }, title),
    createElement("div", { className: "ds-form-section__body" }, children),
  );
}

export type AdvancedSectionProps = {
  children?: ReactNode;
  // Open by itself when one of its fields already holds a value.
  defaultOpen?: boolean;
  label?: string;
  testId?: string;
};

export function AdvancedSection({ children, defaultOpen = false, label = "Advanced", testId = "ds-advanced" }: AdvancedSectionProps) {
  return createElement(
    "details",
    { className: "ds-advanced", open: defaultOpen || undefined, "data-testid": testId },
    createElement("summary", { className: "ds-advanced__summary" }, label),
    createElement("div", { className: "ds-form-section__body" }, children),
  );
}
