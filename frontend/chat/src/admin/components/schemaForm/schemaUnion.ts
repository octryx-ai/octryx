// Never a guess on free values: the discriminator, else a structural match (JSON type + const properties).
import { newEntryValue } from "./schemaDefaults";
import { humanizeKey, isRecord, normalizeField, resolveRef, unionVariants } from "./schemaResolve";
import type { JsonSchema } from "./schemaFormTypes";

export interface UnionVariant {
  index: number;
  branch: JsonSchema;
  label: string;
  tag: string | undefined;
}

export function discriminatorProperty(schema: JsonSchema): string | undefined {
  const discriminator = schema.discriminator;
  if (isRecord(discriminator) && typeof discriminator.propertyName === "string") return discriminator.propertyName;
  return undefined;
}

function constOf(schema: unknown): unknown {
  if (!isRecord(schema)) return undefined;
  if ("const" in schema) return schema.const;
  if (Array.isArray(schema.enum) && schema.enum.length === 1) return schema.enum[0];
  return undefined;
}

function branchTag(root: JsonSchema, branch: JsonSchema, property: string | undefined): string | undefined {
  if (!property || !isRecord(branch.properties)) return undefined;
  const propertySchema = branch.properties[property];
  const tag = isRecord(propertySchema) ? constOf(resolveRef(root, propertySchema)) : undefined;
  return typeof tag === "string" ? tag : undefined;
}

export function unionVariantList(root: JsonSchema, schema: JsonSchema): UnionVariant[] {
  const variants = unionVariants(schema) ?? [];
  const property = discriminatorProperty(schema);
  const mapping = isRecord(schema.discriminator) && isRecord(schema.discriminator.mapping) ? schema.discriminator.mapping : {};
  return variants.map((variant, index) => {
    const raw = isRecord(variant) ? variant : {};
    const branch = normalizeField(root, raw).schema;
    let tag = branchTag(root, branch, property);
    if (tag === undefined && typeof raw.$ref === "string") {
      tag = Object.keys(mapping).find((key) => mapping[key] === raw.$ref);
    }
    const uiLabel = isRecord(branch["x-ui"]) ? branch["x-ui"].label : undefined;
    const title = typeof branch.title === "string" ? humanizeKey(branch.title) : `Variant ${index + 1}`;
    const label = typeof uiLabel === "string" ? uiLabel : tag !== undefined ? humanizeKey(tag) : title;
    return { index, branch, label, tag };
  });
}

function jsonType(value: unknown): string {
  if (value === null) return "null";
  if (Array.isArray(value)) return "array";
  if (typeof value === "number") return Number.isInteger(value) ? "integer" : "number";
  return typeof value;
}

function typeMatches(schemaType: unknown, value: unknown): boolean {
  if (schemaType === undefined) return true;
  const actual = jsonType(value);
  const types = Array.isArray(schemaType) ? schemaType : [schemaType];
  return types.some((type) => type === actual || (type === "number" && actual === "integer"));
}

function structurallyMatches(root: JsonSchema, branch: JsonSchema, value: unknown): boolean {
  if ("const" in branch) return branch.const === value;
  if (Array.isArray(branch.enum)) return branch.enum.includes(value);
  if (!typeMatches(branch.type, value)) return false;
  if (!isRecord(value) || !isRecord(branch.properties)) return true;
  return Object.entries(branch.properties).every(([key, propertySchema]) => {
    if (!isRecord(propertySchema)) return true;
    const expected = constOf(resolveRef(root, propertySchema));
    return expected === undefined || value[key] === expected;
  });
}

export function pickOneOfBranch(
  root: JsonSchema,
  schema: JsonSchema,
  value: unknown,
): { index: number; branch: JsonSchema } | null {
  if (value === undefined) return null;
  const resolved = resolveRef(root, schema);
  const variants = unionVariantList(root, resolved);
  const property = discriminatorProperty(resolved);
  if (property) {
    if (!isRecord(value) || typeof value[property] !== "string") return null;
    const match = variants.find((variant) => variant.tag === value[property]);
    return match ? { index: match.index, branch: match.branch } : null;
  }
  const match = variants.find((variant) => structurallyMatches(root, variant.branch, value));
  return match ? { index: match.index, branch: match.branch } : null;
}

export function switchUnionVariant(root: JsonSchema, branch: JsonSchema, previous: unknown): unknown {
  const next = newEntryValue(root, branch);
  if (!isRecord(next) || !isRecord(previous) || !isRecord(branch.properties)) return next;
  const merged: Record<string, unknown> = { ...next };
  for (const [key, propertySchema] of Object.entries(branch.properties)) {
    if (key in merged || previous[key] === undefined) continue;
    if (isRecord(propertySchema) && "const" in resolveRef(root, propertySchema)) continue;
    merged[key] = previous[key];
  }
  return merged;
}
