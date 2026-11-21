import type { StatusTone } from "../../layout/StatusLabel";

// The CI pipeline on the run view (backend workflow_runs/pipeline.run_view): its state and the audit of its
// last report — which commands ran, from which declaration (the repository's environment file or the repository
// record), on which commit. A red run in file mode also says why the file stopped it (missing, invalid, setup failed).

export type PipelineSetupLine = { command?: string; exit_code?: number | null; output_end?: string };

export type PipelineAudit = {
  source?: "environment_file" | "repository_record" | string;
  file?: string | null;
  app_folder?: string | null;
  sha256?: string | null;
  commands?: string[];
  head?: string;
  device_tree?: string;
  tree?: string;
  file_state?: "ok" | "missing" | "invalid" | "setup_failed" | string;
  file_errors?: string[];
  setup?: PipelineSetupLine[];
};

export type RunPipeline = {
  state?: string | null;
  commands?: string[] | null;
  audit?: PipelineAudit | null;
};

export type PipelineAuditView = {
  label: string;
  tone: StatusTone;
  summary: string;
  problem: string | null;
  errors: string[];
  setup: string[];
  details: string[];
};

const short = (value: string | null | undefined, size = 7) => (value ? value.slice(0, size) : "");
const plural = (count: number) => `${count} command${count === 1 ? "" : "s"}`;
const STATE_LABELS: Record<string, string> = { green: "Passed", red: "Failed", pending: "Running" };

/** Why the environment file stopped the pipeline, in words; null when it did not. */
export function fileStateText(audit: PipelineAudit): string | null {
  const file = audit.file || "the environment file";
  const folder = audit.app_folder && audit.app_folder !== "." ? `${audit.app_folder}/` : "the repository root";
  switch (audit.file_state) {
    case undefined: case null: case "": case "ok": return null;
    case "missing": return `${file} is not in the run's branch, so no tests ran. The agent has to create it.`;
    case "setup_failed": return `The setup commands of ${file} failed in ${folder}, so no tests ran.`;
    default: return `${file} is not a valid environment file, so no tests ran.`;
  }
}

/** The audit block of the run view, or null before the pipeline reported. */
export function pipelineAuditView(pipeline: RunPipeline | null | undefined): PipelineAuditView | null {
  const audit = pipeline?.audit;
  if (!audit) return null;
  const state = String(pipeline?.state ?? "");
  const commands = audit.commands ?? [];
  const fromFile = audit.source === "environment_file";
  const head = short(audit.head);
  const origin = fromFile ? `from ${audit.file}` : "from the repository record";
  const problem = fromFile ? fileStateText(audit) : null;
  const ran = commands.length ? `Ran ${plural(commands.length)}` : "No commands ran";
  const summary = `${ran} ${origin}${head ? ` @ ${head}` : ""}`;
  const details = [
    ...commands.map((command) => `$ ${command}`),
    ...(fromFile ? [`Folder: ${audit.app_folder && audit.app_folder !== "." ? audit.app_folder : "repository root"}`] : []),
    ...(audit.sha256 ? [`File SHA-256: ${short(audit.sha256, 12)}`] : []),
    ...(audit.head ? [`Commit: ${audit.head}`] : []),
    ...(audit.tree ? [`Tree: ${short(audit.tree, 12)}${audit.device_tree && audit.device_tree !== audit.tree
      ? ` (device reported ${short(audit.device_tree, 12)})` : ""}`] : []),
  ];
  const setup = (audit.setup ?? []).filter((line) => line.exit_code !== 0).map((line) =>
    `$ ${line.command ?? ""}\nexit ${line.exit_code ?? "?"}${line.output_end ? `\n${line.output_end}` : ""}`);
  return {
    label: STATE_LABELS[state] ?? (state ? state[0].toUpperCase() + state.slice(1) : "Reported"),
    tone: state === "red" ? "problem" : "neutral",
    summary,
    problem,
    errors: problem ? audit.file_errors ?? [] : [],
    setup: problem ? setup : [],
    details,
  };
}
