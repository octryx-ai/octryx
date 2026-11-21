// Badges of the Agents & workflows area: capability class, enforcement and plain status, on `work-badge`.
export type BadgeKind = "active" | "running" | "attention" | "danger" | "neutral";

export type CapabilityClass = "read_only" | "change" | "deliver";

export type Enforcement = "enforced" | "guided" | "guidance";

const CLASS_BADGES: Record<CapabilityClass, [string, BadgeKind]> = {
  read_only: ["Read-only", "neutral"],
  change: ["Change", "attention"],
  deliver: ["Deliver", "danger"],
};

const ENFORCEMENT_BADGES: Record<Enforcement, [string, BadgeKind]> = {
  enforced: ["Enforced", "active"],
  guided: ["Guided", "running"],
  guidance: ["Guidance only", "neutral"],
};

export function isCapabilityClass(value: unknown): value is CapabilityClass {
  return value === "read_only" || value === "change" || value === "deliver";
}

/** A label in sentence case ("built-in" → "Built-in", "✓ ok" → "✓ Ok"); one that starts with a number is kept. */
export function sentenceCase(text: string): string {
  return text.replace(/^([^A-Za-z0-9]*)([a-z])/, (_match, lead: string, letter: string) => lead + letter.toUpperCase());
}

export function Badge({ kind = "neutral", children }: { kind?: BadgeKind; children: string }) {
  return <span className={`work-badge work-badge--${kind}`}>{sentenceCase(children)}</span>;
}

export function ClassBadge({ value }: { value: unknown }) {
  if (!isCapabilityClass(value)) return <Badge>Unknown class</Badge>;
  const [label, kind] = CLASS_BADGES[value];
  return <Badge kind={kind}>{label}</Badge>;
}

export function classLabel(value: unknown): string {
  return isCapabilityClass(value) ? CLASS_BADGES[value][0] : "Unknown class";
}

export function EnforcedBadge({ value }: { value: Enforcement }) {
  const [label, kind] = ENFORCEMENT_BADGES[value] ?? ENFORCEMENT_BADGES.guidance;
  return <Badge kind={kind}>{label}</Badge>;
}

export function Chip({ children, tone }: { children: string; tone?: "secondary" | "danger" }) {
  return <span className={`admin-policy-chip${tone ? ` admin-policy-chip--${tone}` : ""}`}>{children}</span>;
}
