// One voice capability card of the Workspace voice settings: title, state line, on/off switch and optional fields.
import type { ReactNode } from "react";

const CARD_STYLE = {
  padding: "0.85rem 1rem",
  border: "1px solid var(--border-soft)",
  borderRadius: "var(--ds-radius-md)",
  background: "rgba(255,255,255,0.03)",
  marginBottom: "1rem",
};

const HEAD_STYLE = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
};

export function ProjectVoiceToggleCard({ title, status, enabled, onToggle, headGap, children }: {
  title: string;
  status: string;
  enabled: boolean;
  onToggle: () => void;
  /** Space under the head row when fields follow it. */
  headGap?: string;
  children?: ReactNode;
}) {
  return (
    <div style={CARD_STYLE}>
      <div style={headGap ? { ...HEAD_STYLE, marginBottom: headGap } : HEAD_STYLE}>
        <div>
          <div
            style={{
              fontWeight: 600,
              fontSize: "var(--ds-text-md)",
              marginBottom: "0.15rem",
            }}
          >
            {title}
          </div>
          <div style={{ fontSize: "var(--ds-text-xs)", color: "var(--text-muted)" }}>
            {status}
          </div>
        </div>
        <span
          className={`toggle-switch ${enabled ? "toggle-switch--on" : ""}`}
          onClick={onToggle}
          role="switch"
          aria-checked={enabled}
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === " ") onToggle();
          }}
        />
      </div>
      {children}
    </div>
  );
}
