// The review findings a run went on with (on_open_high: continue_with_findings, run view ``open_findings``): high
// first, the first five shown and the rest one click away. Pure, shared by the run card and the phone's run page.

import type { StatusTone } from "../../layout/StatusLabel";
import { findingPlace, readFindings, type DecisionFinding } from "./decisionCardModel";

export const OPEN_FINDINGS_SHOWN = 5;

export const SEVERITY_TONES: Record<string, StatusTone> = { high: "problem", medium: "attention", low: "neutral" };

/** "High", "Medium", "Low"; "Finding" without a severity. */
export function severityLabel(severity: string): string {
  return severity ? severity[0].toUpperCase() + severity.slice(1) : "Finding";
}

/** "router.py:96", "router.py"; "" for a finding without a file. */
export function findingWhere(finding: DecisionFinding): string {
  return finding.file ? findingPlace(finding) : "";
}

export type OpenFindingsView = { findings: DecisionFinding[]; total: number; more: string };

/** What the list shows: all findings high first, or the first five and "Show all N"; null when there are none. */
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
