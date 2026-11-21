import { DiffEditor, Editor } from "@monaco-editor/react";
import { useEffect, useRef, useState } from "react";

import "./monacoLocal";
import { CEDAR_LANGUAGE_ID, registerCedar } from "./cedarLanguage";
import { CEDAR_THEME_DARK, applyCedarThemes } from "./cedarTheme";
import type { CedarVocabulary } from "./cedarLanguage";
import { schemaVocabulary, validateLive } from "./cedarValidation";
import type { LiveIssue } from "./cedarValidation";

export type CedarEditorProps = {
  value: string;
  onChange: (value: string) => void;
  readOnly: boolean;
  schema: string;
  /** The published text; with `showDiff` the editor shows the draft against it. */
  original: string;
  showDiff: boolean;
  onLiveIssues?: (issues: LiveIssue[] | null) => void;
};

type MonacoApi = Parameters<NonNullable<Parameters<typeof Editor>[0]["beforeMount"]>>[0];
type EditorInstance = Parameters<NonNullable<Parameters<typeof Editor>[0]["onMount"]>>[0];

const OPTIONS = { minimap: { enabled: false }, fontSize: 13, scrollBeyondLastLine: false, wordWrap: "on" as const, tabSize: 2 };

// The Monaco editor for custom Cedar policies: highlighting and schema-aware completion (cedarLanguage), live
// validation in the browser (cedarValidation, debounced) shown as markers, and a diff against the published version.
// Loaded lazily by the Policies page, so Monaco and the wasm module only download when an admin opens it. The theme comes
// from the design tokens (cedarTheme): dark by default, never the white Monaco default.
export default function CedarPolicyEditor({ value, onChange, readOnly, schema, original, showDiff, onLiveIssues }: CedarEditorProps) {
  const monacoRef = useRef<MonacoApi | null>(null);
  const editorRef = useRef<EditorInstance | null>(null);
  const [vocabulary, setVocabulary] = useState<CedarVocabulary | null>(null);
  const [theme, setTheme] = useState(CEDAR_THEME_DARK);

  useEffect(() => {
    let alive = true;
    void schemaVocabulary(schema).then((next) => { if (alive) setVocabulary(next); });
    return () => { alive = false; };
  }, [schema]);

  useEffect(() => {
    if (monacoRef.current && vocabulary) registerCedar(monacoRef.current as never, vocabulary);
  }, [vocabulary]);

  useEffect(() => {
    let alive = true;
    const timer = setTimeout(() => {
      void validateLive(schema, value).then((result) => {
        if (!alive) return;
        onLiveIssues?.(result.available ? result.issues : null);
        const monaco = monacoRef.current;
        const model = editorRef.current?.getModel();
        if (!monaco || !model) return;
        monaco.editor.setModelMarkers(model, "cedar", result.issues.map((item) => {
          const start = model.getPositionAt(item.start);
          const end = model.getPositionAt(Math.max(item.end, item.start + 1));
          return {
            message: item.message,
            severity: item.severity === "error" ? monaco.MarkerSeverity.Error : monaco.MarkerSeverity.Warning,
            startLineNumber: start.lineNumber, startColumn: start.column, endLineNumber: end.lineNumber, endColumn: end.column,
          };
        }));
      });
    }, 400);
    return () => { alive = false; clearTimeout(timer); };
  }, [schema, value, onLiveIssues]);

  const beforeMount = (monaco: MonacoApi) => {
    monacoRef.current = monaco;
    setTheme(applyCedarThemes(monaco as never));
    if (vocabulary) registerCedar(monaco as never, vocabulary);
    else registerCedar(monaco as never, { entityTypes: [], actions: [], attributes: {}, contextFields: [] });
  };

  if (showDiff) {
    return (
      <div className="policies__editor" data-testid="cedar-diff">
        <DiffEditor height="420px" language={CEDAR_LANGUAGE_ID} original={original} modified={value} beforeMount={beforeMount} theme={theme}
          options={{ ...OPTIONS, readOnly: true, renderSideBySide: true }} />
      </div>
    );
  }
  return (
    <div className="policies__editor" data-testid="cedar-editor">
      <Editor height="420px" language={CEDAR_LANGUAGE_ID} value={value} beforeMount={beforeMount} theme={theme}
        onMount={(editor) => { editorRef.current = editor; }}
        onChange={(next) => onChange(next ?? "")} options={{ ...OPTIONS, readOnly }} />
    </div>
  );
}
