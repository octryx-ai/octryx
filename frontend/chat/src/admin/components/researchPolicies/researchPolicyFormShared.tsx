// Field label and shared section props for the research policy structured editor.

export function FieldLabel({ label, hint }: { label: string; hint?: string }) {
  return (
    <label className="research-policy-admin__field-label">
      <span>{label}</span>
      {hint ? <small>{hint}</small> : null}
    </label>
  );
}

export type ResearchPolicySectionProps = {
  spec: Record<string, unknown>;
  setPath: (path: string[], value: unknown) => void;
  setNumberPath: (path: string[], value: string, fallback?: number) => void;
  setListPath: (path: string[], value: string) => void;
};
