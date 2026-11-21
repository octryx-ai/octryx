import type { ReactNode } from "react";

// One collapsible group on the workspace Policies page. Each group keeps the
// save button its form already had; the group only adds a title and purpose.
type ProjectPolicyGroupProps = {
  title: string;
  purpose: string;
  defaultOpen?: boolean;
  children: ReactNode;
};

export function ProjectPolicyGroup({
  title,
  purpose,
  defaultOpen = false,
  children,
}: ProjectPolicyGroupProps) {
  return (
    <details className="project-policy-group" open={defaultOpen}>
      <summary>
        <strong>{title}</strong>
        <span>{purpose}</span>
      </summary>
      <div className="project-policy-group__body">{children}</div>
    </details>
  );
}
