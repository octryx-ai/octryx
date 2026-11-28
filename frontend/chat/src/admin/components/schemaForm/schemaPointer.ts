export function escapePointerSegment(segment: string): string {
  return segment.replace(/~/g, "~0").replace(/\//g, "~1");
}

export function unescapePointerSegment(segment: string): string {
  return segment.replace(/~1/g, "/").replace(/~0/g, "~");
}

export function joinPointer(pointer: string, segment: string | number): string {
  return `${pointer}/${escapePointerSegment(String(segment))}`;
}

export function splitPointer(pointer: string): string[] {
  if (!pointer) return [];
  if (!pointer.startsWith("/")) throw new Error(`Invalid JSON pointer: ${pointer}`);
  return pointer.slice(1).split("/").map(unescapePointerSegment);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isIndex(segment: string): boolean {
  return /^(0|[1-9][0-9]*)$/.test(segment);
}

export function getAtPointer(value: unknown, pointer: string): unknown {
  let current: unknown = value;
  for (const segment of splitPointer(pointer)) {
    if (Array.isArray(current) && isIndex(segment)) current = current[Number(segment)];
    else if (isRecord(current)) current = current[segment];
    else return undefined;
  }
  return current;
}

function setIn(container: unknown, segments: string[], next: unknown): unknown {
  const [head, ...rest] = segments;
  if (Array.isArray(container) && isIndex(head)) {
    const index = Number(head);
    const child = rest.length ? setIn(container[index], rest, next) : next;
    const copy = container.slice();
    if (child === undefined) {
      if (index < copy.length) copy.splice(index, 1);
      return copy;
    }
    copy[index] = child;
    return copy;
  }
  const base: Record<string, unknown> = isRecord(container) ? container : {};
  const existing = base[head];
  if (rest.length && existing === undefined && next === undefined) return base;
  const child = rest.length ? setIn(existing, rest, next) : next;
  const copy: Record<string, unknown> = { ...base };
  if (child === undefined) delete copy[head];
  else copy[head] = child;
  return copy;
}

// Missing intermediate objects are created only when a value is written.
export function setAtPointer(
  value: Record<string, unknown>,
  pointer: string,
  next: unknown,
): Record<string, unknown> {
  const segments = splitPointer(pointer);
  if (!segments.length) return isRecord(next) ? next : {};
  return setIn(value, segments, next) as Record<string, unknown>;
}

export function fieldDomId(prefix: string, pointer: string): string {
  const parts = splitPointer(pointer).map((segment) => segment.replace(/[^A-Za-z0-9_-]/g, (char) => `_${char.charCodeAt(0).toString(16)}`));
  return [prefix, "root", ...parts].join("-");
}
