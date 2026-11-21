// The source choice of a new inbound webhook: one button per sending tool, with the polling hint.
import { AutomationIcon } from "../automation/AutomationIcon";
import type { InboundSource } from "./inboundWebhookModel";

type Props = {
  sources: InboundSource[];
  source: string;
  onPick: (key: string) => void;
};

export function InboundSourceChoice({ sources, source, onPick }: Props) {
  return (
    <div className="admin-panel__field">
      <span>Sends the alerts</span>
      <div className="automation-toolbar">
        {sources.map((option) => (
          <button
            key={option.key}
            type="button"
            aria-pressed={source === option.key}
            className="admin-panel__action-btn automation-choice"
            onClick={() => onPick(option.key)}
          >
            <AutomationIcon kind={option.key} small /> {option.label}
          </button>
        ))}
      </div>
      {sources.find((option) => option.key === source)?.polled ? (
        <small className="automation-muted">
          Checked through its connector every 5 minutes; no URL needed.
        </small>
      ) : null}
    </div>
  );
}
