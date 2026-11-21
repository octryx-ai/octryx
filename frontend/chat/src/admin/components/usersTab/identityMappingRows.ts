// External identity-provider group → local roles / local groups (Sign-in & SSO). The editor works
// on rows and picks local roles and groups by name; the wire form stays `{external_group: [target, …]}` with role
// names and group ids.

export type MappingRow = { external: string; targets: string[] };

export function mappingRows(value: Record<string, string[]> | null | undefined): MappingRow[] {
  return Object.entries(value || {}).map(([external, targets]) => ({ external, targets: [...(targets || [])] }));
}

/** Rows without an external group name or without a target are dropped; duplicate names merge their targets. */
export function mappingRecord(rows: MappingRow[]): Record<string, string[]> {
  const record: Record<string, string[]> = {};
  for (const row of rows) {
    const external = row.external.trim();
    const targets = row.targets.filter(Boolean);
    if (!external || !targets.length) continue;
    record[external] = [...new Set([...(record[external] ?? []), ...targets])];
  }
  return record;
}

/** Rows that will not be saved, with the reason, so the editor can say so before saving. */
export function mappingProblems(rows: MappingRow[]): string[] {
  return rows.flatMap((row, index) => {
    if (!row.external.trim() && row.targets.length) return [`Row ${index + 1}: enter the external group name.`];
    if (row.external.trim() && !row.targets.length) return [`Row ${index + 1}: pick at least one local entry.`];
    return [];
  });
}
