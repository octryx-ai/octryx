import { StatusLabel } from "../../layout/StatusLabel";
import { engineLabel } from "./engineModel";
import "./engines.css";

/** The coding engine of a job, next to its device and model: quiet (neutral), "Claude Code" for a job without one. */
export function EngineBadge({ engine }: { engine: string | null | undefined }) {
  const label = engineLabel(engine);
  return <StatusLabel label={label} tone="neutral" title={`Coding engine: ${label}`} testId="engine-badge" />;
}
