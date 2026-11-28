export type MappingRow = { external: string; targets: string[] };

export function mappingRows(value: Record<string, string[]> | null | undefined): MappingRow[] {
  return Object.entries(value || {}).map(([external, targets]) => ({ external, targets: [...(targets || [])] }));
}

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

export function mappingProblems(rows: MappingRow[]): string[] {
  return rows.flatMap((row, index) => {
    if (!row.external.trim() && row.targets.length) return [`Row ${index + 1}: enter the external group name.`];
    if (row.external.trim() && !row.targets.length) return [`Row ${index + 1}: pick at least one local entry.`];
    return [];
  });
}
