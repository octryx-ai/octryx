import { toolStatusLabel } from "./toolStatusLabel";
import { DiagramViewer } from "./DiagramViewer";

import type { ToolArtifact, ToolEvent } from "../chatThreadTypes";
import { MultilineText } from "./messageBubbleIcons";
import { isObjectRecord } from "./messageBubbleHelpers";
import {
  ConfluenceDeltaInline,
  ConfluenceSyncInline,
} from "./messageBubbleInlineConfluence";
import { INLINE_TOOL_EVENT_NAMES } from "./messageBubbleInlineTools.helpers";
import { ToolArtifacts } from "./messageBubbleToolArtifacts";

type PreviewArtifact = ((artifact: ToolArtifact) => void) | undefined;

function renderSavedScript(event: ToolEvent) {
  const parameters = event.parameters ?? {};
  const scriptName =
    typeof parameters.name === "string"
      ? parameters.name
      : "saved_python_script";
  const purpose =
    typeof parameters.purpose === "string" ? parameters.purpose : "";
  const code = typeof parameters.code === "string" ? parameters.code : "";
  return (
    <section className="tool-inline tool-inline--script">
      <div className="tool-inline__header">
        <span className="tool-inline__badge">Python script saved</span>
        <span
          className={`tool-inline__status tool-inline__status--${event.status}`}
        >
          {toolStatusLabel(event.status)}
        </span>
      </div>
      <div className="tool-inline__title">{scriptName}</div>
      <div className="tool-inline__meta-row">
        <span className="tool-inline__meta-pill">generated artifact</span>
      </div>
      {purpose ? <div className="tool-inline__text">{purpose}</div> : null}
      {code ? (
        <details className="tool-inline__details">
          <summary className="tool-inline__summary">
            View generated code
          </summary>
          <pre className="tool-inline__pre">{code}</pre>
        </details>
      ) : null}
    </section>
  );
}

function renderScriptRun(event: ToolEvent, result: Record<string, unknown>, onPreviewArtifact: PreviewArtifact) {
  const artifacts = event.artifacts ?? [];
  const scriptName =
    typeof result.name === "string" ? result.name : "saved_python_script";
  const exitCode =
    typeof result.exit_code === "number" ? result.exit_code : null;
  const stdout = typeof result.stdout === "string" ? result.stdout : "";
  const stderr = typeof result.stderr === "string" ? result.stderr : "";
  return (
    <section className="tool-inline tool-inline--execution">
      <div className="tool-inline__header">
        <span className="tool-inline__badge">Python execution</span>
        <span
          className={`tool-inline__status tool-inline__status--${event.status}`}
        >
          {toolStatusLabel(event.status)}
        </span>
      </div>
      <div className="tool-inline__title">
        {scriptName}
        {exitCode !== null ? (
          <span className="tool-inline__exit">exit {exitCode}</span>
        ) : null}
      </div>
      <div className="tool-inline__meta-row">
        {artifacts.length ? (
          <span className="tool-inline__meta-pill">
            {artifacts.length} generated{" "}
            {artifacts.length === 1 ? "artifact" : "artifacts"}
          </span>
        ) : null}
      </div>
      {stdout.trim() ? (
        <details className="tool-inline__details">
          <summary className="tool-inline__summary">
            View execution output
          </summary>
          <MultilineText value={stdout} />
        </details>
      ) : null}
      {stderr.trim() ? (
        <details className="tool-inline__details">
          <summary className="tool-inline__summary">
            View error output
          </summary>
          <MultilineText
            value={stderr}
            className="tool-inline__pre tool-inline__pre--error"
          />
        </details>
      ) : null}
      <ToolArtifacts
        artifacts={artifacts}
        onPreviewArtifact={onPreviewArtifact}
      />
    </section>
  );
}

// Octryx may move large tool results into artifact storage.
// The actual payload is then at result.preview.compact_result.<field>.
function diagramFields(result: Record<string, unknown>) {
  const compact =
    result.preview != null &&
    typeof result.preview === "object" &&
    "compact_result" in (result.preview as object)
      ? ((result.preview as Record<string, unknown>).compact_result as Record<
          string,
          unknown
        >)
      : null;
  const effective = compact ?? result;
  const isExternalized =
    typeof result._artifact_storage === "string" &&
    result._artifact_storage === "external_json_gzip";

  const diagramXml =
    typeof effective.diagram_xml === "string" ? effective.diagram_xml : "";
  const title =
    typeof effective.title === "string" ? effective.title : "Diagram";
  const diagramId =
    typeof effective.diagram_id === "string"
      ? effective.diagram_id
      : undefined;
  const changeDesc =
    typeof effective.change_description === "string"
      ? effective.change_description
      : "";
  return { isExternalized, diagramXml, title, diagramId, changeDesc };
}

function renderDiagram(event: ToolEvent, result: Record<string, unknown>, onPreviewArtifact: PreviewArtifact) {
  const artifacts = event.artifacts ?? [];
  const { isExternalized, diagramXml, title, diagramId, changeDesc } = diagramFields(result);
  return (
    <section className="tool-inline tool-inline--diagram">
      <div className="tool-inline__meta-row">
        {diagramId ? (
          <>
            <span className="tool-inline__meta-label">diagram id</span>
            <code className="tool-inline__code">{diagramId}</code>
          </>
        ) : null}
      </div>
      {changeDesc ? (
        <div className="tool-inline__text">{changeDesc}</div>
      ) : null}
      {/* Large diagrams are externalized and only carry a truncated XML in
          the chat payload; the viewer then lazily fetches the full XML from
          the artifact endpoint so it still renders inline. */}
      {isExternalized && diagramId ? (
        <DiagramViewer
          title={title}
          diagramId={diagramId}
          fetchUrl={`/chat/api/artifact?path=${encodeURIComponent(`diagram://${diagramId}`)}`}
        />
      ) : diagramXml ? (
        <DiagramViewer xml={diagramXml} title={title} diagramId={diagramId} />
      ) : (
        <div className="tool-inline__text tool-inline__text--error">
          No diagram XML returned.
        </div>
      )}
      <ToolArtifacts
        artifacts={artifacts}
        onPreviewArtifact={onPreviewArtifact}
      />
    </section>
  );
}

function InlineToolExecution({
  event,
  onPreviewArtifact,
}: {
  event: ToolEvent;
  onPreviewArtifact?: (artifact: ToolArtifact) => void;
}) {
  const result = isObjectRecord(event.result) ? event.result : {};
  if (event.toolName === "save_python_script") return renderSavedScript(event);
  if (event.toolName === "run_saved_python_script") return renderScriptRun(event, result, onPreviewArtifact);

  if (event.toolName === "list_confluence_page_updates") {
    return <ConfluenceDeltaInline event={event} result={result} />;
  }

  if (event.toolName === "sync_confluence_knowledge_map") {
    return <ConfluenceSyncInline event={event} result={result} />;
  }

  if (
    event.toolName === "create_diagram" ||
    event.toolName === "edit_diagram"
  ) {
    return renderDiagram(event, result, onPreviewArtifact);
  }

  return null;
}

export function InlineToolExecutions({
  events,
  onPreviewArtifact,
}: {
  events: ToolEvent[];
  onPreviewArtifact?: (artifact: ToolArtifact) => void;
}) {
  const inlineEvents = events.filter((event) =>
    INLINE_TOOL_EVENT_NAMES.has(event.toolName),
  );
  if (!inlineEvents.length) {
    return null;
  }
  return (
    <div className="tool-inline-list">
      {inlineEvents.map((event) => (
        <InlineToolExecution
          key={event.id}
          event={event}
          onPreviewArtifact={onPreviewArtifact}
        />
      ))}
    </div>
  );
}
