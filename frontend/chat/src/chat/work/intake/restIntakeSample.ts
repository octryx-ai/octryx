// Custom REST Work source: the dry run's answer as the preview table shows it.

import { str } from "./restIntakeForm";

export type SampleRow = { key: string; title: string; status: string; becomes: string; extra: string };

export type SampleView = {
  rows: SampleRow[];
  read: number;
  mapped: number;
  closed: number;
  lastPage: boolean;
  role: string;
  dropped: number;
  droppedReasons: string[];
};

const count = (value: unknown) => (typeof value === "number" && Number.isFinite(value) && value > 0 ? value : 0);

/** The dry run's answer (`POST …/intake/sample`) as the preview shows it: one table row per mapped item, the dropped
 * entries with their reasons. */
export function sampleView(answer: Record<string, unknown>, workStates: Array<{ key: string; label: string }>): SampleView {
  const items = Array.isArray(answer.items) ? (answer.items as Array<Record<string, unknown>>) : [];
  const stateLabel = (key: unknown) => workStates.find((state) => state.key === key)?.label ?? str(key);
  const rows = items.map((item) => {
    const labels = Array.isArray(item.labels_json) ? item.labels_json.map(str).filter(Boolean) : [];
    const extra = [
      item.issue_type ? `type ${str(item.issue_type)}` : "",
      item.reporter ? `reporter ${str(item.reporter)}` : "",
      item.assignee ? `assignee ${str(item.assignee)}` : "",
      item.parent_key ? `parent ${str(item.parent_key)}` : "",
      labels.length ? `labels ${labels.join(", ")}` : "",
    ].filter(Boolean).join(" · ");
    return { key: str(item.source_key), title: str(item.title), status: str(item.source_status), becomes: stateLabel(item.work_state), extra };
  });
  const invalid = count(answer.skipped_invalid);
  const outOfScope = count(answer.dropped_out_of_scope);
  const reasons = [
    invalid ? `${invalid} without a key, title or status` : "",
    outOfScope ? `${outOfScope} outside the role's data scope` : "",
  ].filter(Boolean);
  const read = count(answer.records);
  return { rows, read, mapped: Math.max(read - invalid, 0), closed: count(answer.closed), lastPage: answer.last_page === true,
    role: str(answer.role), dropped: invalid + outOfScope, droppedReasons: reasons };
}
