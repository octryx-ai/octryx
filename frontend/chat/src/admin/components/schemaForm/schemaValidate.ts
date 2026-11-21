// Cheap local checks for inline feedback. The server validator stays authoritative.
import { joinPointer, splitPointer } from "./schemaPointer";
import { classifySchema, isRecord, mapValueSchema, normalizeField, requiredSet } from "./schemaResolve";
import { pickOneOfBranch } from "./schemaUnion";
import type { JsonSchema, SchemaFormErrors } from "./schemaFormTypes";

const MAX_DEPTH = 32;
const patternCache = new Map<string, RegExp | null>();

function compilePattern(pattern: string): RegExp | null {
  if (!patternCache.has(pattern)) {
    try {
      patternCache.set(pattern, new RegExp(pattern, "u"));
    } catch {
      patternCache.set(pattern, null);
    }
  }
  return patternCache.get(pattern) ?? null;
}

function push(errors: SchemaFormErrors, pointer: string, message: string): void {
  (errors[pointer] ??= []).push(message);
}

function num(schema: JsonSchema, key: string): number | undefined {
  const value = schema[key];
  return typeof value === "number" ? value : undefined;
}

function display(value: unknown): string {
  return typeof value === "string" ? `"${value}"` : JSON.stringify(value);
}

function checkString(schema: JsonSchema, value: string, pointer: string, errors: SchemaFormErrors): void {
  const minLength = num(schema, "minLength");
  const maxLength = num(schema, "maxLength");
  const length = [...value].length;
  if (minLength !== undefined && length < minLength) {
    push(errors, pointer, minLength === 1 ? "Must not be empty" : `At least ${minLength} characters`);
  }
  if (maxLength !== undefined && length > maxLength) push(errors, pointer, `At most ${maxLength} characters`);
  if (typeof schema.pattern === "string" && length > 0) {
    const regex = compilePattern(schema.pattern);
    if (regex && !regex.test(value)) push(errors, pointer, `Invalid format (expected ${schema.pattern})`);
  }
}

function checkNumber(schema: JsonSchema, value: number, integer: boolean, pointer: string, errors: SchemaFormErrors): void {
  if (integer && !Number.isInteger(value)) push(errors, pointer, "Must be a whole number");
  const minimum = num(schema, "minimum");
  const maximum = num(schema, "maximum");
  const exclusiveMinimum = num(schema, "exclusiveMinimum");
  const exclusiveMaximum = num(schema, "exclusiveMaximum");
  if (minimum !== undefined && value < minimum) push(errors, pointer, `Must be at least ${minimum}`);
  if (maximum !== undefined && value > maximum) push(errors, pointer, `Must be at most ${maximum}`);
  if (exclusiveMinimum !== undefined && value <= exclusiveMinimum) push(errors, pointer, `Must be greater than ${exclusiveMinimum}`);
  if (exclusiveMaximum !== undefined && value >= exclusiveMaximum) push(errors, pointer, `Must be less than ${exclusiveMaximum}`);
}

function checkObject(root: JsonSchema, schema: JsonSchema, value: Record<string, unknown>, pointer: string, errors: SchemaFormErrors, depth: number): void {
  const properties = isRecord(schema.properties) ? schema.properties : {};
  for (const key of requiredSet(schema)) {
    if (value[key] === undefined) push(errors, joinPointer(pointer, key), "Required");
  }
  const patternProperties = isRecord(schema.patternProperties) ? schema.patternProperties : {};
  const valueSchema = mapValueSchema(schema);
  for (const [key, child] of Object.entries(value)) {
    const childPointer = joinPointer(pointer, key);
    if (child === undefined) continue;
    if (isRecord(properties[key])) {
      walk(root, properties[key] as JsonSchema, child, childPointer, errors, depth + 1);
      continue;
    }
    const patternMatch = Object.entries(patternProperties).find(([pattern]) => compilePattern(pattern)?.test(key));
    if (patternMatch && isRecord(patternMatch[1])) {
      walk(root, patternMatch[1], child, childPointer, errors, depth + 1);
    } else if (isRecord(schema.additionalProperties)) {
      walk(root, schema.additionalProperties, child, childPointer, errors, depth + 1);
    } else if (schema.additionalProperties === false || (Object.keys(patternProperties).length && valueSchema)) {
      push(errors, childPointer, Object.keys(patternProperties).length ? "Invalid key name" : "Unknown field");
    }
    if (isRecord(schema.propertyNames)) {
      const keyErrors: SchemaFormErrors = {};
      checkString(schema.propertyNames, key, childPointer, keyErrors);
      for (const message of keyErrors[childPointer] ?? []) push(errors, childPointer, `Key: ${message}`);
    }
  }
  const count = Object.keys(value).length;
  const minProperties = num(schema, "minProperties");
  const maxProperties = num(schema, "maxProperties");
  if (minProperties !== undefined && count < minProperties) push(errors, pointer, `At least ${minProperties} ${minProperties === 1 ? "entry" : "entries"}`);
  if (maxProperties !== undefined && count > maxProperties) push(errors, pointer, `At most ${maxProperties} entries`);
}

function checkArray(root: JsonSchema, schema: JsonSchema, value: unknown[], pointer: string, errors: SchemaFormErrors, depth: number): void {
  const minItems = num(schema, "minItems");
  const maxItems = num(schema, "maxItems");
  if (minItems !== undefined && value.length < minItems) push(errors, pointer, `At least ${minItems} ${minItems === 1 ? "item" : "items"}`);
  if (maxItems !== undefined && value.length > maxItems) push(errors, pointer, `At most ${maxItems} items`);
  if (schema.uniqueItems === true && new Set(value.map((item) => JSON.stringify(item))).size !== value.length) {
    push(errors, pointer, "Items must be unique");
  }
  if (isRecord(schema.items)) {
    value.forEach((item, index) => walk(root, schema.items as JsonSchema, item, joinPointer(pointer, index), errors, depth + 1));
  }
}

function walk(root: JsonSchema, rawSchema: JsonSchema, value: unknown, pointer: string, errors: SchemaFormErrors, depth: number): void {
  if (depth > MAX_DEPTH || value === undefined) return;
  const { schema, nullable } = normalizeField(root, rawSchema);
  if (value === null) {
    if (!nullable && schema.type !== "null" && classifySchema(schema) !== "any") push(errors, pointer, "Must not be empty");
    return;
  }
  switch (classifySchema(schema)) {
    case "const":
      if (value !== schema.const) push(errors, pointer, `Must be ${display(schema.const)}`);
      return;
    case "enum":
      if (!(schema.enum as unknown[]).includes(value)) push(errors, pointer, "Not an allowed option");
      return;
    case "union": {
      const picked = pickOneOfBranch(root, schema, value);
      if (!picked) push(errors, pointer, "Choose a variant");
      else walk(root, picked.branch, value, pointer, errors, depth + 1);
      return;
    }
    case "string":
      if (typeof value !== "string") push(errors, pointer, "Must be text");
      else checkString(schema, value, pointer, errors);
      return;
    case "integer":
    case "number":
      if (typeof value !== "number" || !Number.isFinite(value)) push(errors, pointer, "Must be a number");
      else checkNumber(schema, value, schema.type === "integer", pointer, errors);
      return;
    case "boolean":
      if (typeof value !== "boolean") push(errors, pointer, "Must be true or false");
      return;
    case "object":
    case "map":
      if (!isRecord(value)) push(errors, pointer, "Must be an object");
      else checkObject(root, schema, value, pointer, errors, depth);
      return;
    case "array":
      if (!Array.isArray(value)) push(errors, pointer, "Must be a list");
      else checkArray(root, schema, value, pointer, errors, depth);
      return;
    default:
      return;
  }
}

/**
 * Cheap local checks keyed by JSON pointer relative to `value`: required,
 * const/enum, string length/pattern, number bounds, integer, array/map sizes,
 * unknown keys. Missing required fields are reported at the field's pointer.
 */
export function clientFieldErrors(root: JsonSchema, schema: JsonSchema, value: unknown): SchemaFormErrors {
  const errors: SchemaFormErrors = {};
  walk(root, schema, value, "", errors, 0);
  return errors;
}

export function mergeErrors(...sources: Array<SchemaFormErrors | undefined>): SchemaFormErrors {
  const merged: SchemaFormErrors = {};
  for (const source of sources) {
    for (const [pointer, messages] of Object.entries(source ?? {})) {
      for (const message of messages) {
        const list = (merged[pointer] ??= []);
        if (!list.includes(message)) list.push(message);
      }
    }
  }
  return merged;
}

/**
 * Messages no field shows: root-level messages and those under an undeclared
 * top-level property. Hidden fields are the host's to render (with their errors).
 * The form lists the orphans in a summary so nothing is silently dropped.
 */
export function orphanErrors(rootObject: JsonSchema, errors: SchemaFormErrors, hiddenFields: readonly string[]): Array<[string, string]> {
  const properties = isRecord(rootObject.properties) ? rootObject.properties : {};
  const result: Array<[string, string]> = [];
  for (const [pointer, messages] of Object.entries(errors)) {
    const head = pointer ? splitPointer(pointer)[0] : undefined;
    const placed = head !== undefined && (head in properties || hiddenFields.includes(head));
    if (!placed) messages.forEach((message) => result.push([pointer, message]));
  }
  return result;
}
