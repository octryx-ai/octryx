import "./corpIdentity.css";

type Brief = Record<string, unknown> | null;

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function Swatches({ colors }: { colors: Record<string, unknown> }) {
  const entries = Object.entries(colors).filter((entry): entry is [string, string] => typeof entry[1] === "string");
  if (entries.length === 0) return <span className="admin-panel__cell--muted">—</span>;
  return (
    <div className="corp-swatches">
      {entries.map(([slot, hex]) => (
        <div key={slot} className="corp-swatch" title={`${slot} ${hex}`}>
          {/* The one dynamic value: the extracted colour itself. */}
          <div className="corp-swatch__color" style={{ background: hex }} />
          <div className="corp-swatch__hex">{hex}</div>
        </div>
      ))}
    </div>
  );
}

// The corporate identity extracted from a profile's templates (fonts, neutrals, accents per medium, assets). Read-only
// (no manual overrides: document generation and the prompt read the templates) — change the templates to change
// the identity.
export function CorpIdentityBrandSheet({ profileId, brief }: { profileId: string; brief: Brief }) {
  if (!brief) {
    return (
      <section className="user-edit-panel__section">
        <p className="user-edit-panel__section-label">Corporate identity</p>
        <p className="admin-panel__hint">Being extracted from this profile&apos;s templates…</p>
      </section>
    );
  }
  const fonts = asRecord(brief.fonts);
  const neutrals = asRecord(brief.neutrals);
  const accents = asRecord(brief.accents_by_medium);
  const assets = asRecord(brief.assets);
  const counts = asRecord(assets.counts);
  const summary = asRecord(brief.summary);
  const conflicts = Array.isArray(brief.conflicts) ? brief.conflicts : [];
  const logos = Array.isArray(assets.logos) ? (assets.logos as Record<string, unknown>[]) : [];
  const media = Array.isArray(summary.media) ? (summary.media as string[]).join(" · ") : "—";
  const assetUrl = (path: string) =>
    `/admin/chat/api/panel/corp-identities/${encodeURIComponent(profileId)}/asset?path=${encodeURIComponent(path)}`;

  return (
    <section className="user-edit-panel__section" data-testid="corp-brand-sheet">
      <div className="corp-brand__head">
        <p className="user-edit-panel__section-label">Corporate identity</p>
        <div className="corp-brand__badges">
          <span className="task-item__badge task-item__badge--secondary">{String(summary.source_count ?? "0")} templates</span>
          <span className="task-item__badge task-item__badge--secondary">{media}</span>
          <span className={`task-item__badge ${conflicts.length ? "" : "task-item__badge--secondary"}`}>
            {conflicts.length} {conflicts.length === 1 ? "conflict" : "conflicts"}
          </span>
        </div>
      </div>
      <div className="corp-brand__body">
        <div>
          <div className="corp-identity-detail__label">Font &amp; neutrals</div>
          <p className="corp-brand__font">{typeof fonts.major === "string" && fonts.major ? fonts.major : "No font found in the templates."}</p>
          <Swatches colors={neutrals} />
        </div>
        {Object.keys(accents).length > 0 ? (
          <div>
            <div className="corp-identity-detail__label">Accents per medium</div>
            <div className="corp-brand__accents">
              {Object.entries(accents).map(([medium, colors]) => (
                <div key={medium}>
                  <div className="corp-brand__medium">{medium}</div>
                  <Swatches colors={asRecord(colors)} />
                </div>
              ))}
            </div>
          </div>
        ) : null}
        <div>
          <div className="corp-identity-detail__label">
            Assets · {String(counts.logos ?? 0)} logos · {String(counts.icons ?? 0)} icons · {String(counts.images ?? 0)} images
          </div>
          {logos.length > 0 ? (
            <div className="corp-brand__logos">
              {logos.slice(0, 6).map((logo, index) => (
                <img key={index} className="corp-brand__logo" src={assetUrl(String(logo.path ?? ""))} alt={String(logo.name ?? "logo")} />
              ))}
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}
