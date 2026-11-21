// A page a session made, shown sandboxed on the phone; the rules are in pagePolicy.ts.

import { useState } from "react";
import { pageSrcDoc } from "./pagePolicy";

export function SandboxedPage({ html, title }: { html: string; title: string }) {
  const [full, setFull] = useState(false);
  const [source, setSource] = useState(false);
  const frame = (
    <iframe
      className={full ? "m-page-frame m-page-frame-full" : "m-page-frame"}
      title={title}
      sandbox="allow-scripts"
      referrerPolicy="no-referrer"
      srcDoc={pageSrcDoc(html)}
    />
  );
  return (
    <div className="m-page">
      <div className="m-page-bar">
        <button type="button" className="m-copy" onClick={() => setFull(true)}>
          Full screen
        </button>
        <button type="button" className="m-copy" onClick={() => setSource((value) => !value)}>
          {source ? "Page" : "Source"}
        </button>
      </div>
      {source ? <pre>{html}</pre> : !full && frame}
      {full && (
        <div className="m-page-overlay" role="dialog" aria-label={title}>
          <div className="m-page-overlay-bar">
            <strong>{title}</strong>
            <button type="button" className="m-copy" onClick={() => setFull(false)}>
              Close
            </button>
          </div>
          {frame}
        </div>
      )}
    </div>
  );
}
