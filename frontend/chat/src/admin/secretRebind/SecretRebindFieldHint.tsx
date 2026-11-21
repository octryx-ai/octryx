import { rebindFieldHint, rebindFieldRole } from "./secretRebindFlow";
import type { SecretRebindFlow } from "./secretRebindFlow";

// The refusal's note next to one field: a changed target, a kept secret, or a kept secret still lacking its new value.
export function SecretRebindFieldHint({ flow, field }: { flow: SecretRebindFlow<unknown> | null; field: string }) {
  const role = rebindFieldRole(flow, field);
  if (!flow || !role) return null;
  return (
    <span className={`security-field-hint security-field-hint--${role === "missing_secret" ? "error" : "attention"}`}>
      {rebindFieldHint(role, flow.step)}
    </span>
  );
}
