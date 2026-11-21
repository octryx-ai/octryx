import { useEffect, useState } from "react";

import { CheckRow } from "./SkillBadges";
import { SkillMarkdown } from "./SkillMarkdown";
import { loadDelivery } from "./skillCatalogApi";
import { formatSize, reasonLabel, refusalText } from "./skillCatalogModel";
import type { DeliveryPreview } from "./skillDeliveryTypes";
import type { SkillVersion } from "./skillCatalogTypes";
import { pluginLayout, referenceFiles } from "./skillDetailModel";

// Detail → Delivery (mock `deliveryHtml`, `mcpDeliveryHtml`): what an octryx-claude session receives from the working
// version (plugin layout, delivered files, stripped frontmatter keys, withheld scripts, the delivered SKILL.md) and how
// platform chat offers it; for an MCP server entry the delivered server, image digest and the variables left unset.
export function SkillDeliveryTab({ skillId, name, version }: { skillId: string; name: string; version: SkillVersion }) {
  const [preview, setPreview] = useState<DeliveryPreview | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    loadDelivery(skillId, version.version)
      .then((raw) => { if (alive) setPreview(raw as DeliveryPreview); })
      .catch((error: unknown) => { if (alive) setProblem(refusalText(error)); });
    return () => { alive = false; };
  }, [skillId, version.version]);

  if (problem) return <p className="policies__warn" role="alert">{problem}</p>;
  if (!preview) return <p className="admin-panel__hint" role="status">Loading the delivery preview…</p>;
  if (preview.kind === "mcp_server") return <McpDelivery name={name} preview={preview} version={version} />;
  const references = referenceFiles(version.files);
  return (
    <div data-testid="skill-delivery">
      <div className="admin-panel__card">
        <div className="admin-panel__section-header">octryx-claude · what a session receives</div>
        {!version.available_octryx_claude ? <p className="policies__note">This version is not available on octryx-claude; the preview shows what it would receive.</p> : null}
        {preview.deliverable === false ? <p className="policies__warn">{reasonLabel("name_not_deliverable")}: this skill cannot be delivered to octryx-claude.</p> : null}
        <dl className="work-detail__kv">
          <dt>Command</dt><dd className="skills__mono">{preview.command ?? "—"}</dd>
          <dt>Files</dt><dd>{preview.files.map((file) => `${file.path} (${formatSize(file.size)})`).join(", ") || "—"}</dd>
          <dt>Stripped keys</dt><dd>{preview.stripped_keys.length ? preview.stripped_keys.map((key, index) => <span key={key}>{index ? ", " : ""}<span className="admin-policy-inline-code">{key}</span></span>) : "none"}</dd>
          <dt>Withheld</dt><dd>{preview.scripts_withheld.length ? preview.scripts_withheld.join(", ") : "no scripts withheld"}</dd>
        </dl>
        <pre className="policies__code skill-detail__gap" data-testid="skill-delivery-layout">{pluginLayout(preview.plugin, name, preview.files)}</pre>
        <CheckRow tone="in" icon="1">At start the launcher asks the platform for the Workspace&apos;s skill manifest (names, versions, file digests),
          downloads only bundles it does not have, verifies every file digest and refuses the session on a mismatch
          (<span className="admin-policy-inline-code">skill_bundle_digest_mismatch</span>).</CheckRow>
        <CheckRow tone="in" icon="2">It writes a per-session plugin (read-only files) and passes <span className="admin-policy-inline-code">--plugin-dir</span>.
          Nothing is written to <span className="admin-policy-inline-code">~/.claude</span> or to the repository.</CheckRow>
        <CheckRow tone="in" icon="3">Session settings add <span className="admin-policy-inline-code">&quot;disableSkillShellExecution&quot;: true</span>; hooks
          report each use. The skill files can be read but not edited by the agent.</CheckRow>
        {preview.skill_md ? (
          <div className="skill-detail__gap">
            <div className="skills__tree-label">Delivered SKILL.md</div>
            <SkillMarkdown text={preview.skill_md} testId="skill-delivery-md" />
          </div>
        ) : null}
      </div>
      <div className="admin-panel__card skill-detail__gap">
        <div className="admin-panel__section-header">Platform chat</div>
        {!version.available_platform_chat ? <p className="policies__note">This version is not available on platform chat.</p> : null}
        <p className="admin-panel__hint">
          <span className="admin-policy-inline-code">skill_search</span> returns the name and description;{" "}
          <span className="admin-policy-inline-code">skill_get</span> returns the card (description and section outline) or the full SKILL.md,
          and a single reference file with <span className="admin-policy-inline-code">resource=&quot;&lt;path&gt;&quot;</span>
          {references.length ? <> ({references.map((file) => file.path).join(", ")})</> : null}. Scripts and assets that need execution are
          never offered in chat.
        </p>
      </div>
    </div>
  );
}

function McpDelivery({ name, preview, version }: { name: string; preview: DeliveryPreview; version: SkillVersion }) {
  const unset = preview.env_unset ?? [];
  return (
    <div data-testid="skill-delivery">
      <div className="admin-panel__card">
        <div className="admin-panel__section-header">octryx-claude</div>
        {!version.available_octryx_claude ? <p className="policies__note">This version is not available on octryx-claude.</p> : null}
        <CheckRow tone="in" icon="1">The manifest lists MCP server entries separately from skills. The launcher writes{" "}
          <span className="skills__mono">{name}</span> into the per-session plugin&apos;s <span className="skills__mono">.mcp.json</span>{" "}
          <b>only</b> if the Workspace MCP policy allows it; otherwise the entry is omitted and the start banner says so.</CheckRow>
        <CheckRow tone={preview.image_digest ? "in" : "wa"} icon="2">
          {preview.image_digest ? <>Image by digest <span className="skills__mono">{preview.image_digest}</span>. </>
            : <>No image digest recorded: the entry is not delivered until the review records it. </>}
          {unset.length ? <>{unset.map((key) => <span key={key} className="skills__mono">{key} </span>)}come from the Workspace&apos;s named connection or stay unset. </> : null}
          Environment variables of the user&apos;s shell are not passed through.
        </CheckRow>
        <CheckRow tone="in" icon="3">Every tool the server exposes is called as{" "}
          <span className="admin-policy-inline-code">mcp__plugin_{preview.plugin}_{name}__&lt;tool&gt;</span> and goes through the
          PreToolUse tool-check, the MCP policy and the platform policies like any other MCP tool.</CheckRow>
        {preview.server ? <pre className="policies__code skill-detail__gap" data-testid="skill-delivery-server">{JSON.stringify({ [name]: preview.server }, null, 2)}</pre> : null}
      </div>
      <div className="admin-panel__card skill-detail__gap">
        <div className="admin-panel__section-header">Platform chat</div>
        <p className="admin-panel__hint">Not available. A stdio server that runs a local process cannot run inside the platform. A remote MCP
          endpoint is registered as a connector with its own named connection, not through this entry.</p>
      </div>
    </div>
  );
}
