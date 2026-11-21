// Cedar for Monaco: syntax highlighting (Monarch) and schema-aware completion. The vocabulary comes from the
// server's schema (converted to JSON by cedar-wasm), never from a hard-coded list, so a schema change reaches the
// editor without a frontend change.

type Json = Record<string, unknown>;
const isRecord = (value: unknown): value is Json => typeof value === "object" && value !== null && !Array.isArray(value);

export const CEDAR_LANGUAGE_ID = "cedar";

export const CEDAR_KEYWORDS = [
  "permit", "forbid", "when", "unless", "principal", "action", "resource", "context", "in", "has", "like", "is",
  "if", "then", "else", "true", "false",
];

export const CEDAR_MONARCH = {
  keywords: CEDAR_KEYWORDS,
  operators: ["==", "!=", "<", "<=", ">", ">=", "&&", "||", "!", "+", "-", "*"],
  tokenizer: {
    root: [
      [/@[a-zA-Z_][\w]*/, "annotation"],
      [/[A-Z][\w]*(?=::)/, "type"],
      [/[a-zA-Z_][\w]*/, { cases: { "@keywords": "keyword", "@default": "identifier" } }],
      [/\/\/.*$/, "comment"],
      [/"/, { token: "string.quote", next: "@string" }],
      [/\d+/, "number"],
      [/[{}()[\]]/, "@brackets"],
      [/[=!<>&|+\-*]+/, "operator"],
      [/[;,.:]/, "delimiter"],
    ],
    string: [
      [/[^\\"]+/, "string"],
      [/\\./, "string.escape"],
      [/"/, { token: "string.quote", next: "@pop" }],
    ],
  },
};

export type CedarVocabulary = {
  entityTypes: string[];
  actions: string[];
  attributes: Record<string, string[]>;
  contextFields: string[];
};

function recordFields(shape: unknown, commonTypes: Json): string[] {
  let value = shape;
  if (isRecord(value) && typeof value.type === "string" && isRecord(commonTypes[value.type])) value = commonTypes[value.type];
  if (!isRecord(value) || !isRecord(value.attributes)) return [];
  return Object.keys(value.attributes).sort();
}

/** The completion vocabulary of a schema in Cedar's JSON form (`schemaToJson`), all namespaces merged. */
export function vocabularyOf(schemaJson: unknown): CedarVocabulary {
  const vocabulary: CedarVocabulary = { entityTypes: [], actions: [], attributes: {}, contextFields: [] };
  if (!isRecord(schemaJson)) return vocabulary;
  const context = new Set<string>();
  for (const namespace of Object.values(schemaJson)) {
    if (!isRecord(namespace)) continue;
    const commonTypes = isRecord(namespace.commonTypes) ? namespace.commonTypes : {};
    for (const [name, definition] of Object.entries(isRecord(namespace.entityTypes) ? namespace.entityTypes : {})) {
      vocabulary.entityTypes.push(name);
      vocabulary.attributes[name] = recordFields(isRecord(definition) ? definition.shape : null, commonTypes);
    }
    for (const [name, definition] of Object.entries(isRecord(namespace.actions) ? namespace.actions : {})) {
      vocabulary.actions.push(name);
      const applies = isRecord(definition) && isRecord(definition.appliesTo) ? definition.appliesTo : {};
      for (const field of recordFields(applies.context, commonTypes)) context.add(field);
    }
  }
  vocabulary.entityTypes.sort();
  vocabulary.actions.sort();
  vocabulary.contextFields = [...context].sort();
  return vocabulary;
}

export type CedarSuggestion = { label: string; insertText: string; kind: "keyword" | "type" | "action" | "field"; detail: string };

/** What to offer after the text before the cursor (`linePrefix`): attributes after `x.`, actions after `Action::`. */
export function suggestionsFor(linePrefix: string, vocabulary: CedarVocabulary): CedarSuggestion[] {
  if (/Action::"?[\w]*$/.test(linePrefix)) {
    const quoted = /Action::"[\w]*$/.test(linePrefix);
    return vocabulary.actions.map((name) => ({
      label: name, insertText: quoted ? name : `"${name}"`, kind: "action", detail: "action",
    }));
  }
  if (/\bcontext\.[\w]*$/.test(linePrefix)) {
    return vocabulary.contextFields.map((name) => ({ label: name, insertText: name, kind: "field", detail: "context" }));
  }
  if (/\b(principal|resource|context\.workspace)\.[\w]*$/.test(linePrefix)) {
    const seen = new Map<string, string[]>();
    for (const [type, fields] of Object.entries(vocabulary.attributes)) {
      for (const field of fields) seen.set(field, [...(seen.get(field) ?? []), type]);
    }
    return [...seen.entries()].sort().map(([name, types]) => ({
      label: name, insertText: name, kind: "field", detail: types.join(", "),
    }));
  }
  return [
    ...CEDAR_KEYWORDS.map((word): CedarSuggestion => ({ label: word, insertText: word, kind: "keyword", detail: "keyword" })),
    ...vocabulary.entityTypes.map((type): CedarSuggestion => ({ label: type, insertText: `${type}::""`, kind: "type", detail: "entity type" })),
    { label: "Action", insertText: 'Action::""', kind: "type", detail: "action reference" },
    {
      label: "forbid…", kind: "keyword", detail: "custom policy skeleton",
      insertText: '@id("my-policy")\nforbid (principal, action == Action::"run_command", resource)\nwhen { resource.prefixes.contains("") };',
    },
  ];
}

type MonacoLike = {
  languages: {
    getLanguages(): { id: string }[];
    register(language: { id: string }): void;
    setMonarchTokensProvider(id: string, rules: unknown): void;
    registerCompletionItemProvider(id: string, provider: unknown): { dispose(): void };
    CompletionItemKind: Record<string, number>;
  };
};

let completionDisposable: { dispose(): void } | null = null;

/** Registers the language once and (re)binds completion to the current vocabulary. */
export function registerCedar(monaco: MonacoLike, vocabulary: CedarVocabulary): void {
  if (!monaco.languages.getLanguages().some((language) => language.id === CEDAR_LANGUAGE_ID)) {
    monaco.languages.register({ id: CEDAR_LANGUAGE_ID });
    monaco.languages.setMonarchTokensProvider(CEDAR_LANGUAGE_ID, CEDAR_MONARCH);
  }
  completionDisposable?.dispose();
  const kinds = monaco.languages.CompletionItemKind;
  const kindOf = { keyword: kinds.Keyword, type: kinds.Class, action: kinds.Event, field: kinds.Field };
  completionDisposable = monaco.languages.registerCompletionItemProvider(CEDAR_LANGUAGE_ID, {
    triggerCharacters: [".", ":", '"'],
    provideCompletionItems(model: { getValueInRange(range: unknown): string; getWordUntilPosition(position: unknown): { startColumn: number; endColumn: number } }, position: { lineNumber: number; column: number }) {
      const prefix = model.getValueInRange({ startLineNumber: position.lineNumber, startColumn: 1, endLineNumber: position.lineNumber, endColumn: position.column });
      const word = model.getWordUntilPosition(position);
      const range = { startLineNumber: position.lineNumber, endLineNumber: position.lineNumber, startColumn: word.startColumn, endColumn: word.endColumn };
      return {
        suggestions: suggestionsFor(prefix, vocabulary).map((item) => ({
          label: item.label, insertText: item.insertText, kind: kindOf[item.kind], detail: item.detail, range,
        })),
      };
    },
  });
}
