import type { ProblemList } from "../../admin/components/problems/problemsModel";

export const WORK_PROBLEM_KINDS = ["intake", "run", "rule_denial"];

// A stalled device job is a run's item that stopped working, so it belongs to Work; other device problems keep their own page.
const isWorkProblem = (problem: ProblemList["problems"][number]) =>
  WORK_PROBLEM_KINDS.includes(problem.kind) || (problem.kind === "device" && problem.object?.type === "device_job");
export const KNOWLEDGE_PROBLEM_KINDS = ["sync"];

export type WorkProblemsLine = { text: string; tone: "problem" | "attention"; target: "work" | "knowledge" } | null;

/** Problem tone when any is a problem; null when there is none. */
export function workProblemsLine(list: ProblemList | null): WorkProblemsLine {
  if (!list) return null;
  const work = list.problems.filter(isWorkProblem);
  if (!work.length) {
    const knowledge = list.problems.filter((problem) => KNOWLEDGE_PROBLEM_KINDS.includes(problem.kind));
    if (!knowledge.length) return null;
    const failing = knowledge.some((problem) => problem.severity === "problem");
    return { text: `${knowledge.length} Knowledge ${knowledge.length === 1 ? "problem" : "problems"}`,
      tone: failing ? "problem" : "attention", target: "knowledge" };
  }
  const problems = work.filter((problem) => problem.severity === "problem").length;
  const attention = work.length - problems;
  const problemText = `${problems} ${problems === 1 ? "problem" : "problems"}`;
  const text = !attention ? problemText
    : !problems ? `${attention} ${attention === 1 ? "needs" : "need"} attention`
      : `${problemText} and ${attention} needing attention`;
  return { text: `${text} in Work`, tone: problems ? "problem" : "attention", target: "work" };
}
