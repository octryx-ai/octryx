import type { StatusTone } from "../../layout/StatusLabel";
import { findingPlace, readFindings, type DecisionFinding } from "./decisionCardModel";

export const OPEN_FINDINGS_SHOWN = 5;

export const SEVERITY_TONES: Record<string, StatusTone> = { high: "problem", medium: "attention", low: "neutral" };

export function severityLabel(severity: string): string {
  return severity ? severity[0].toUpperCase() + severity.slice(1) : "Finding";
}

export function findingWhere(finding: DecisionFinding): string {
  return finding.file ? findingPlace(finding) : "";
}

export type OpenFindingsView = { findings: DecisionFinding[]; total: number; more: string };

export function openFindingsView(value: unknown, showAll: boolean): OpenFindingsView | null {
  const all = readFindings(value);
  if (!all.length) return null;
  const folded = !showAll && all.length > OPEN_FINDINGS_SHOWN;
  return {
    findings: folded ? all.slice(0, OPEN_FINDINGS_SHOWN) : all,
    total: all.length,
    more: folded ? `Show all ${all.length}` : "",
  };
}
