import type { PayloadView } from "./workflowRunPayloadView";

export type PublishProve = {
  publication?: { page_id?: string; version?: number; published_at?: string;
    acceptance_as_published?: string; acceptance_as_of?: string } | null;
  acceptance?: { state?: string; as_of?: string; late?: boolean };
  acceptance_history?: Array<{ decision?: string; at?: string; reason?: string }>;
  audience?: Record<string, boolean>;
  followup?: { key?: string; url?: string; read_back?: boolean } | null;
};

const text = (value: unknown) => value === null || value === undefined ? "" : String(value);
const record = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
const list = (value: unknown): string[] => Array.isArray(value) ? value.map(String) : [];

/** Separate human statements: never imply that publishing a page accepts the feature. */
export function publishProvePayload(subject: string, payload: Record<string, unknown>): PayloadView | null {
  const headings: Record<string, string> = {
    functional_acceptance: "Functional acceptance (a)", publication: "Publication (b)",
    followup: "Authorise this follow-up", exception: "Declared exception",
  };
  if (!(subject in headings)) return null;
  const lines: string[] = [];
  const target = record(payload.target);
  if (subject === "functional_acceptance") {
    const build = record(payload.build);
    if (build.tested_sha) lines.push(`Observed tested commit: ${text(build.tested_sha)}`);
    if (build.ci_url) lines.push(`CI evidence: ${text(build.ci_url)}`);
    if (build.note) lines.push(text(build.note));
    if (payload.pending_since) lines.push(`Acceptance pending since ${text(payload.pending_since)}`);
    const published = record(payload.published);
    if (published.page_id) lines.push(`Published page ${text(published.page_id)} version ${text(published.version)}`);
    if (payload.refresh_note) lines.push(text(payload.refresh_note));
  }
  if (subject === "publication") {
    lines.push(`Page: ${text(payload.title)}`, `Site: ${text(target.instance)}`,
      `Connection: ${text(target.connection_id)}`, `Space: ${text(target.space_key)}`,
      `Parent: ${text(target.parent_id)}`, text(target.summary));
    if (payload.acceptance_pending) lines.push(`Acceptance pending as of ${text(payload.acceptance_as_of)}`);
    const audience = record(payload.audience);
    lines.push(`Audience: ${text(audience.semantics)}`);
    if (payload.run_link) lines.push(`Workflow record: ${text(payload.run_link)}`);
  }
  if (subject === "followup") {
    lines.push(`Project: ${text(payload.project_key)}`, `Issue type: ${text(payload.issue_type)}`,
      `Summary: ${text(payload.summary)}`, `Owner: ${text(payload.owner)}`);
  }
  if (subject === "exception") {
    lines.push(`Missing proof: ${text(payload.missing_proof)}`, `Owner: ${text(payload.owner)}`,
      `Read-back follow-up: ${text(payload.followup_key)}`);
  }
  for (const item of Array.isArray(payload.acceptance_criteria) ? payload.acceptance_criteria : []) {
    const criterion = record(item);
    lines.push(`${text(criterion.id)}: ${text(criterion.text)}`);
  }
  return { heading: headings[subject], lines: lines.filter(Boolean),
    blockers: [...list(payload.blockers), ...list(payload.accept_blockers)],
    missing: typeof payload.missing === "string" ? payload.missing : null,
    text: text(payload.statement || payload.description) || null, testAlert: null };
}

export function publishProveStatus(view: PublishProve | null | undefined): string[] {
  if (!view) return [];
  const lines: string[] = [];
  const page = view.publication;
  if (page?.page_id) {
    lines.push(`Published page ${page.page_id} version ${page.version} at ${page.published_at ?? "unknown time"}`);
    if (page.acceptance_as_published === "pending") {
      lines.push(`That page version records acceptance pending as of ${page.acceptance_as_of ?? "publication"}.`);
    }
  }
  if (view.acceptance?.state) lines.push(`Functional acceptance: ${view.acceptance.state}${
    view.acceptance.as_of ? ` · ${view.acceptance.as_of}` : ""}`);
  if (view.acceptance?.late) lines.push("The later decision is recorded here; the published page was not edited.");
  if (view.followup?.key) lines.push(`Follow-up ${view.followup.key}${view.followup.read_back ? " · read back" : ""}`);
  return lines;
}

export function documentationContractLines(value: unknown): string[] {
  const contract = record(value);
  if (!Object.keys(contract).length) return [];
  const audience = record(contract.audience);
  return [`Documentation space: ${text(contract.space_key)} · parent ${text(contract.parent_page_id)}`,
    `Documentation audience: ${text(audience.semantics) || "not configured"}`,
    `Documentation owner: ${text(contract.doc_owner)}`, `Documentation timing: ${text(contract.timing)}`,
    ...list(contract.not_configured).map(item => `Documentation not configured: ${item}`)];
}
