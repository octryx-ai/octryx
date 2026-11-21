import type { ReactNode } from "react";

// Small shared pieces of the REST API pages: a labelled field with its hint and refusal, and a block of warnings.

// `group`: a field with several controls (a secret with Replace and Clear) is a group, not a label, so a click on
// its name does not press the first button.
export function Field({ label, hint, error, children, testId, group = false }: {
  label: string;
  hint?: ReactNode;
  error?: string | null;
  children: ReactNode;
  testId?: string;
  group?: boolean;
}) {
  const body = (
    <>
      <span>{label}</span>
      {children}
      {hint ? <small className="rst-hint">{hint}</small> : null}
      {error ? <small className="rst-field__error" role="alert">{error}</small> : null}
    </>
  );
  return group
    ? <div className="admin-panel__field rst-field" role="group" aria-label={label} data-testid={testId}>{body}</div>
    : <label className="admin-panel__field rst-field" data-testid={testId}>{body}</label>;
}

export type WarningItem = string | { text: string; onOpen?: () => void };

// A warning with `onOpen` (it names an operation) is a link to that operation.
export function Warnings({ items, testId = "rest-warnings", label }: { items: WarningItem[]; testId?: string; label?: string }) {
  if (!items.length) return null;
  return (
    <ul className="rst-warnings" data-testid={testId} aria-label={label}>
      {items.map((item) => {
        const { text, onOpen } = typeof item === "string" ? { text: item, onOpen: undefined } : item;
        return (
          <li key={text}>
            {onOpen ? <button type="button" className="rst-warning-link" onClick={onOpen}>{text}</button> : text}
          </li>
        );
      })}
    </ul>
  );
}

export function FormError({ text }: { text: string | null }) {
  return text ? <p className="rst-error" role="alert">{text}</p> : null;
}

export const Mono = ({ children }: { children: ReactNode }) => <code className="rst-mono">{children}</code>;
