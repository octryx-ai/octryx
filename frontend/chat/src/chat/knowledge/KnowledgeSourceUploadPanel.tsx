import { useId, useState } from "react";
import type { FormEvent } from "react";
import { SidePanel } from "../../layout/SidePanel";
import { workspaceKnowledgeApi } from "../../admin/components/workspaceKnowledge/workspaceKnowledgeApi";
import type { UploadResult } from "../../admin/components/workspaceKnowledge/workspaceKnowledgeTypes";
import { KnowledgeFileField, KnowledgeUploadGuide } from "../../admin/components/workspaceKnowledge/KnowledgeUploadFields";
import { declaredUploadFile, sourceKeyOf } from "../../admin/components/workspaceKnowledge/knowledgeUploadPolicy";
import type { ChosenUpload } from "../../admin/components/workspaceKnowledge/knowledgeUploadPolicy";

export function KnowledgeSourceUploadPanel({ workspaceId, onUploaded, onClose }: {
  workspaceId: string; onUploaded: () => void; onClose: () => void;
}) {
  const id = useId();
  const [chosen, setChosen] = useState<ChosenUpload | null>(null);
  const [title, setTitle] = useState("");
  const [sourceKey, setSourceKey] = useState("");
  const [products, setProducts] = useState("");
  const [version, setVersion] = useState("");
  const [result, setResult] = useState<UploadResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const close = () => {
    if (busy) return;
    if (!dirty || window.confirm("Discard this document upload and its unsaved fields?")) onClose();
  };
  const upload = async (event: FormEvent) => {
    event.preventDefault();
    if (!chosen || busy) return;
    const body = new FormData();
    body.append("file", declaredUploadFile(chosen));
    body.append("source_key", sourceKey.trim() || sourceKeyOf(chosen.file.name));
    body.append("display_title", title.trim() || chosen.file.name);
    if (products.trim()) body.append("products", products.trim());
    if (products.trim() && version.trim()) body.append("version", version.trim());
    setBusy(true); setError(null); setResult(null);
    try { setResult(await workspaceKnowledgeApi.upload(workspaceId, body)); setDirty(false); onUploaded(); }
    catch (failure) { setError(failure instanceof Error ? failure.message : String(failure)); }
    finally { setBusy(false); }
  };
  // The shared side panel over the dimmed list, Cancel and the primary bottom right, like every other
  // create flow. After an upload the panel stays open with the result.
  return <SidePanel title="Add document" subtitle="Knowledge · Documents" onClose={close} testId="knowledge-upload-panel"
    footer={<>
      <button type="button" className="admin-panel__action-btn" disabled={busy} onClick={close}>{result ? "Done" : "Cancel"}</button>
      <button type="submit" form={`${id}-form`} className="admin-panel__action-btn admin-panel__action-btn--primary" disabled={!chosen || busy}>
        {busy ? "Uploading…" : "Upload document"}</button>
    </>}>
    <form id={`${id}-form`} className="knowledge-upload-drawer__form" onSubmit={(event) => void upload(event)}
      onChange={() => { setDirty(true); setResult(null); }}>
      <fieldset disabled={busy}>
        <legend className="knowledge-upload-drawer__legend">Document and source options</legend>
        <KnowledgeFileField id={`${id}-file`} chosen={chosen} onChange={(next) => { setChosen(next); setResult(null); }} />
        <KnowledgeUploadGuide id={`${id}-file`} chosen={chosen} />
        <label className="admin-panel__field">Title (optional)<input className="admin-panel__input" value={title} maxLength={300}
          placeholder="Defaults to the file name" onChange={(event) => setTitle(event.target.value)} /></label>
        <details><summary>Version and source options</summary>
          <label>Source key (optional)<input className="admin-panel__input" value={sourceKey} maxLength={200}
            onChange={(event) => setSourceKey(event.target.value)} /></label>
          <p className="admin-panel__note">Reuse a source key to add a new revision of an existing document.</p>
          <label>Products (optional)<input className="admin-panel__input" value={products} maxLength={500}
            onChange={(event) => setProducts(event.target.value)} /></label>
          <label>Version (requires products)<input className="admin-panel__input" value={version} maxLength={40}
            disabled={!products.trim()} onChange={(event) => setVersion(event.target.value)} /></label>
        </details>
      </fieldset>
      {error ? <p role="alert">{error}</p> : null}
      {result ? <p role="status">Revision {result.revision_ordinal} uploaded.
        {result.projection === "parsing" ? " It is being parsed now; refresh to see when it is indexed." :
          ` ${result.span_count} passages parsed; it is searchable once indexed.`}
        {!result.created ? " These exact bytes were already uploaded, so no new revision was created." : ""}</p> : null}
    </form>
  </SidePanel>;
}
