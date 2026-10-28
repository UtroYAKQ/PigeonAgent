/** 从 JSON schema 推出生成式表单的字段；没有 schema 时退化成单个文本框。 */
export interface SchemaField {
  key: string;
  label: string;
  type: "text" | "textarea" | "number" | "boolean" | "select";
  required: boolean;
  options: string[];
}

export type FieldValues = Record<string, string | number | boolean>;

function propertyEntries(parameters: Record<string, unknown>): [string, Record<string, unknown>][] {
  const properties = parameters.properties;
  if (typeof properties !== "object" || properties === null) return [];
  return Object.entries(properties as Record<string, unknown>).filter(
    (entry): entry is [string, Record<string, unknown>] => typeof entry[1] === "object",
  );
}

function fieldOf(key: string, schema: Record<string, unknown>, required: boolean): SchemaField {
  const options = Array.isArray(schema.enum) ? schema.enum.map(String) : [];
  const type = String(schema.type ?? "string");
  return {
    key,
    label: String(schema.title ?? key),
    required,
    options,
    type: options.length
      ? "select"
      : type === "boolean"
        ? "boolean"
        : type === "number" || type === "integer"
          ? "number"
          : String(schema.format ?? "") === "textarea"
            ? "textarea"
            : "text",
  };
}

export function fieldsOf(parameters: Record<string, unknown>): SchemaField[] {
  const required = new Set(Array.isArray(parameters.required) ? parameters.required.map(String) : []);
  return propertyEntries(parameters).map(([key, schema]) => fieldOf(key, schema, required.has(key)));
}

function filled(value: unknown): boolean {
  return typeof value === "boolean" || (value != null && String(value).trim() !== "");
}

export function readyFor(parameters: Record<string, unknown>, value: unknown): boolean {
  const fields = fieldsOf(parameters);
  if (fields.length === 0) return filled(value);
  const record = (value ?? {}) as FieldValues;
  return fields.every((field) => !field.required || filled(record[field.key]));
}

export function resultFor(parameters: Record<string, unknown>, value: unknown): unknown {
  const fields = fieldsOf(parameters);
  if (fields.length === 0) return typeof value === "string" ? value.trim() : value;
  const record = (value ?? {}) as FieldValues;
  return Object.fromEntries(
    fields.filter((field) => filled(record[field.key])).map((field) => [field.key, record[field.key]]),
  );
}
