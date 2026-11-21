import type { ReactNode } from "react";

import { countValues, extractNamedValues } from "./codingSessionValues";
import { arrayValue, compactUrlLabel, isHttpUrl } from "./codingDetailValues";

// Small shared parts of the Coding session detail:
// labelled values, evidence lists and external links.

export function EvidenceList({
  title,
  values,
  emptyText = "No evidence captured yet.",
}: {
  title: string;
  values: unknown;
  emptyText?: string;
}) {
  const entries = arrayValue(values);
  return (
    <section className="coding-detail__evidence">
      <h3>{title}</h3>
      {entries.length === 0 ? <p className="work-detail__empty">{emptyText}</p> : null}
      {entries.length > 0 ? (
        <ul>
          {entries.map((entry, index) => (
            <li key={`${title}-${index}`}>
              <CompactJson value={entry} />
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

export function KeyValue({ label, value }: { label: string; value: ReactNode }) {
  return (
    <dl className="coding-detail__kv">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </dl>
  );
}

export function ExternalLinkList({
  links,
  emptyText,
}: {
  links: Array<{ label: string; href?: string | null }>;
  emptyText: string;
}) {
  const visible = links.filter((link) => link.label);
  if (visible.length === 0) {
    return <span>{emptyText}</span>;
  }
  return (
    <span className="coding-link-list">
      {visible.map((link) => (
        <ExternalEvidenceLink key={`${link.label}-${link.href || ""}`} href={link.href} label={link.label} />
      ))}
    </span>
  );
}

export function ExternalEvidenceLink({ href, label }: { href?: string | null; label: string }) {
  if (!href || !isHttpUrl(href)) {
    return <span>{label}</span>;
  }
  return (
    <a className="coding-external-link" href={href} target="_blank" rel="noreferrer">
      {label}
    </a>
  );
}

export function CompactJson({ value }: { value: unknown }) {
  if (typeof value === "string") {
    if (isHttpUrl(value)) {
      return <ExternalEvidenceLink href={value} label={compactUrlLabel(value)} />;
    }
    return <span>{value}</span>;
  }
  if (value == null) {
    return <span>Not captured.</span>;
  }
  const named = extractNamedValues(value);
  if (named.length > 0 && countValues(value) <= 1) {
    return <span>{named.join(", ")}</span>;
  }
  return <pre>{JSON.stringify(value, null, 2)}</pre>;
}
