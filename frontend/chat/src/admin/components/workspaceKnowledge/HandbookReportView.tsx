// "Handbook vs. reality" lists: every item cites the manual page/section and the file line.
import type { ReactNode } from "react";

import { EntityGraphCitation } from "../entityGraph/EntityGraphCitation";
import type { FindingItem, HandbookReport, ParameterItem, StructuredCitation } from "./structuredGraphApi";
import { displayValue, reportSummary, variantsNote } from "./structuredGraphModel";

function Cite({ citation, workspaceId }: { citation: StructuredCitation | null; workspaceId: string }) {
  return citation ? <EntityGraphCitation evidence={citation} workspaceId={workspaceId} />
    : <div className="admin-panel__note">Citation not available to you.</div>;
}

function Hints({ hints, workspaceId }: { hints: ParameterItem[]; workspaceId: string }) {
  return hints.length ? <div className="admin-panel__note">
    The manual documents the same name elsewhere:{" "}
    {hints.map((hint) => (
      <span key={hint.parameter}>{hint.parameter}{hint.default ? ` (default ${hint.default})` : ""}
        <Cite citation={hint.citation} workspaceId={workspaceId} /></span>
    ))}
  </div> : null;
}

function Variants({ item }: { item: FindingItem }) {
  const note = variantsNote(item.variants);
  return note ? <div className="admin-panel__note">{note}</div> : null;
}

function shown(item: FindingItem): string {
  const value = displayValue(item.value, item.redacted);
  return item.resolved_value ? `${value} = ${item.resolved_value}` : value;
}

export function HandbookReportView({ report, workspaceId }: { report: HandbookReport; workspaceId: string }) {
  return (
    <div className="admin-panel__stack">
      <p className="admin-panel__note" role="status">{reportSummary(report)}</p>
      <ReportSection label="Undocumented settings in sections the manual knows" heading="Undocumented settings in sections the manual knows" items={report.undocumented_in_known_section}
        render={(item) => undocumentedItem(item, workspaceId)} />
      <ReportSection label="Sections unknown to the manual" heading="Sections unknown to the manual" items={report.unknown_section}
        render={(item) => unknownSectionItem(item, workspaceId)} />
      <ReportSection label="Deviations from documented defaults" heading="Deviations from documented defaults" items={report.deviations}
        render={(item) => deviationItem(item, workspaceId)} />
      <ReportSection label="Unresolved placeholders" heading="Unresolved placeholders (not compared with the default)" items={report.unresolved_placeholders}
        render={(item) => placeholderItem(item, workspaceId)} />
      <ReportSection label="Different values across components" heading="Different values across components" items={report.inconsistencies}
        render={(item) => inconsistencyItem(item, workspaceId)} />
      <ReportSection label="Documented but never set" heading="Documented but never set" items={report.documented_unused}
        render={(item) => unusedItem(item, workspaceId)} />
    </div>
  );
}

// One list of the report under its heading, or "None.".
function ReportSection<T>({ label, heading, items, render }: {
  label: string; heading: string; items: T[]; render: (item: T) => ReactNode;
}) {
  return (
    <section aria-label={label}>
      <h4>{heading}</h4>
      {items.length ? <ul>
        {items.map(render)}
      </ul> : <p className="admin-panel__note">None.</p>}
    </section>
  );
}

// A setting the manual does not document, in a section it knows.
function undocumentedItem(item: HandbookReport["undocumented_in_known_section"][number], workspaceId: string) {
  return (
    <li key={`${item.file}:${item.line}`}>
      <strong>{item.setting}</strong> = {shown(item)} ({item.component}, {item.file} line {item.line})
      <Cite citation={item.citation} workspaceId={workspaceId} />
      <Variants item={item} />
      <Hints hints={item.name_matches} workspaceId={workspaceId} />
    </li>
  );
}

// A section the manual does not know, with its first keys.
function unknownSectionItem(item: HandbookReport["unknown_section"][number], workspaceId: string) {
  return (
    <li key={`${item.file}:${item.line}`}>
      <strong>{item.section ? `[${item.section}]` : item.file}</strong> ({item.component}, {item.file} line
      {" "}{item.line}): {item.key_count} keys — {item.keys.slice(0, 12).join(", ")}
      {item.key_count > 12 ? ", …" : ""}
      {item.variant_files.length ? <div className="admin-panel__note">also in {item.variant_files.join(", ")}</div> : null}
      <Cite citation={item.citation} workspaceId={workspaceId} />
      <Hints hints={item.name_matches} workspaceId={workspaceId} />
    </li>
  );
}

// A value that differs from the documented default.
function deviationItem(item: HandbookReport["deviations"][number], workspaceId: string) {
  return (
    <li key={`${item.file}:${item.line}`}>
      <strong>{item.setting}</strong> = {shown(item)} in {item.component}; documented
      default {item.documented.default}{item.documented.unit ? ` ${item.documented.unit}` : ""}
      <Cite citation={item.citation} workspaceId={workspaceId} />
      <Cite citation={item.documented.citation} workspaceId={workspaceId} />
      <Variants item={item} />
    </li>
  );
}

// A value with a placeholder that nothing defines.
function placeholderItem(item: HandbookReport["unresolved_placeholders"][number], workspaceId: string) {
  return (
    <li key={`${item.file}:${item.line}`}>
      <strong>{item.setting}</strong> = {displayValue(item.value, item.redacted)} in {item.component};
      {" "}no definition of {item.placeholders.join(", ")}
      <Cite citation={item.citation} workspaceId={workspaceId} />
      <Variants item={item} />
    </li>
  );
}

// One setting with its values across the components.
function inconsistencyItem(group: HandbookReport["inconsistencies"][number], workspaceId: string) {
  return (
    <li key={group.setting}><strong>{group.setting}</strong>
      <ul>{group.values.map((value) => (
        <li key={`${value.file}:${value.line}`}>{value.component}: {displayValue(value.value, value.redacted)}
          {value.compared_value && value.compared_value !== value.value ? ` = ${value.compared_value}` : ""}
          <Cite citation={value.citation} workspaceId={workspaceId} />
          <Variants item={value} /></li>
      ))}</ul>
    </li>
  );
}

// A documented parameter that no file sets.
function unusedItem(item: HandbookReport["documented_unused"][number], workspaceId: string) {
  return (
    <li key={item.parameter}><strong>{item.parameter}</strong>{item.default ? ` (default ${item.default})` : ""}
      {" "}— not set in {item.files.join(", ")}
      <Cite citation={item.citation} workspaceId={workspaceId} /></li>
  );
}
