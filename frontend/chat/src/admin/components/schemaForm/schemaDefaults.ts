import { classifySchema, isRecord, normalizeField, requiredSet } from "./schemaResolve";
import type { JsonSchema } from "./schemaFormTypes";

const MAX_DEPTH = 16;

function skeleton(root: JsonSchema, schema: JsonSchema, depth: number): unknown {
  if (depth > MAX_DEPTH) return undefined;
  const { schema: field, nullable } = normalizeField(root, schema);
  if (nullable) return undefined;
  switch (classifySchema(field)) {
    case "const":
      return field.const;
    case "enum":
      return Array.isArray(field.enum) && field.enum.length === 1 ? field.enum[0] : undefined;
    case "object": {
      const properties = isRecord(field.properties) ? field.properties : {};
      const result: Record<string, unknown> = {};
      for (const key of requiredSet(field)) {
        const propertySchema = properties[key];
        if (!isRecord(propertySchema)) continue;
        const child = skeleton(root, propertySchema, depth + 1);
        if (child !== undefined) result[key] = child;
      }
      return result;
    }
    case "map":
      return {};
    case "array":
      return [];
    default:
      // Unions stay unset: the variant is an explicit choice.
      return undefined;
  }
}

export function defaultValueFor(root: JsonSchema, schema: JsonSchema): unknown {
  return skeleton(root, schema, 0);
}

export function newEntryValue(root: JsonSchema, schema: JsonSchema): unknown {
  const value = defaultValueFor(root, schema);
  if (value !== undefined) return value;
  const field = normalizeField(root, schema).schema;
  switch (classifySchema(field)) {
    case "string":
      return "";
    case "object":
    case "map":
      return {};
    default:
      return null;
  }
}
