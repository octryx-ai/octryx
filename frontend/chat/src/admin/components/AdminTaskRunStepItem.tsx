import type { StepLogEntryRow } from "./taskTypes";

function getStepStatusStyles(status: string) {
  if (status === "success") {
    return { color: "var(--status-active-ink)", background: "var(--status-active-soft)", border: "var(--status-active)" };
  }
  if (status === "error") {
    return { color: "var(--status-error-ink)", background: "var(--status-error-soft)", border: "var(--status-error)" };
  }
  if (status === "skipped") {
    return { color: "var(--muted)", background: "var(--surface-overlay)", border: "var(--border)" };
  }
  return { color: "var(--status-attention-ink)", background: "var(--status-attention-soft)", border: "var(--status-attention)" };
}

type AdminTaskRunStepItemProps = {
  step: StepLogEntryRow;
};

export function AdminTaskRunStepItem({ step }: AdminTaskRunStepItemProps) {
  const styles = getStepStatusStyles(step.status);
  return (
    <div
      style={{
        background: styles.background,
        border: `1px solid ${styles.border}`,
        borderRadius: "var(--ds-radius-sm)",
        padding: "0.4rem 0.6rem",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "0.4rem",
          flexWrap: "wrap",
        }}
      >
        <span
          style={{
            fontFamily: "monospace",
            fontSize: "var(--ds-text-2xs)",
            color: "var(--muted)",
            minWidth: "1rem",
            textAlign: "right",
          }}
        >
          {step.position}
        </span>
        <span style={{ fontWeight: 600, fontSize: "var(--ds-text-sm)" }}>
          {step.name || step.step_id}
        </span>
        <span
          style={{
            fontSize: "var(--ds-text-2xs)",
            padding: "0.1rem 0.35rem",
            background: "var(--surface-overlay)",
            border: "1px solid #e5e7eb",
            borderRadius: "var(--ds-radius-sm)",
            color: "var(--muted)",
          }}
        >
          {step.step_type}
        </span>
        <span
          style={{
            fontSize: "var(--ds-text-2xs)",
            fontWeight: 600,
            textTransform: "uppercase",
            color: styles.color,
          }}
        >
          {step.status}
        </span>
        {step.fix_attempts > 0 ? (
          <span style={{ fontSize: "var(--ds-text-2xs)", color: "var(--status-attention-ink)" }}>
            {step.fix_attempts} fix{step.fix_attempts > 1 ? "es" : ""}
          </span>
        ) : null}
        {step.session_ids.map((sid) => (
          <a
            key={sid}
            href={`/chat?session_id=${sid}`}
            target="_blank"
            rel="noopener noreferrer"
            style={{ fontSize: "var(--ds-text-2xs)", color: "var(--status-running-ink)" }}
            onClick={(event) => event.stopPropagation()}
          >
            session ↗
          </a>
        ))}
        {step.output_keys.length > 0 ? (
          <span style={{ fontSize: "var(--ds-text-2xs)", color: "var(--muted)" }}>
            → {step.output_keys.join(", ")}
          </span>
        ) : null}
      </div>
      {step.error ? (
        <div
          style={{
            marginTop: "0.3rem",
            fontSize: "var(--ds-text-xs)",
            fontFamily: "monospace",
            color: "var(--status-error-ink)",
            whiteSpace: "pre-wrap",
            background: "var(--status-error-soft)",
            borderRadius: "var(--ds-radius-sm)",
            padding: "0.3rem 0.5rem",
          }}
        >
          {step.error}
        </div>
      ) : null}
    </div>
  );
}
