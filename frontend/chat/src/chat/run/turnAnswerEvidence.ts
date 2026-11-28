// unsourced renders as an explicit turn-scoped marker, so it does not read as missing links; an unknown value renders nothing.

export const TURN_ANSWER_EVIDENCE_STATES = [
  "passed",
  "reminded",
  "refused",
  "unsourced",
  "marked",
] as const;

export type TurnAnswerEvidenceState =
  (typeof TURN_ANSWER_EVIDENCE_STATES)[number];

export type TurnAnswerEvidence = {
  state: TurnAnswerEvidenceState;
  citedCount: number | null;
  uncitedCount: number | null;
};

export type TurnAnswerEvidencePresentation = {
  tone: "success" | "neutral" | "attention";
  label: string;
  description: string;
  explain?: boolean;
};

function count(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 0
    ? value
    : null;
}

export function parseTurnAnswerEvidence(value: unknown): TurnAnswerEvidence | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  const state = record.evidence_guard;
  if (!TURN_ANSWER_EVIDENCE_STATES.includes(state as TurnAnswerEvidenceState)) {
    return null;
  }
  return {
    state: state as TurnAnswerEvidenceState,
    citedCount: count(record.cited_count),
    uncitedCount: count(record.uncited_count),
  };
}

export function presentAnswerEvidence(
  evidence: TurnAnswerEvidence | null,
): TurnAnswerEvidencePresentation | null {
  if (!evidence) return null;
  switch (evidence.state) {
    case "passed":
      return {
        tone: "success",
        label: "Sources cited",
        description: "Every statement links a source from this turn's evidence.",
      };
    case "refused":
      return {
        tone: "attention",
        label: "Answer withheld",
        description: "The answer did not cite its sources and was withheld.",
      };
    case "marked":
      return {
        tone: "attention",
        label: "Some claims unsourced",
        description:
          "The answer is shown in full; each claim without a source and each link not found in this turn's evidence is marked in place.",
        explain: true,
      };
    case "unsourced":
      return {
        tone: "neutral",
        label: "No source evidence this turn",
        description:
          "No supporting source is recorded for this turn. Sources lists links cited in the answer; they have not been checked against evidence from this turn.",
        explain: true,
      };
    default:
      return null;
  }
}
