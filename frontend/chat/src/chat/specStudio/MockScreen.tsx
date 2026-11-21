import { useContext, useState, type CSSProperties, type ReactNode } from "react";

import { MockAssetsContext } from "./mockAssets";

import { isStudioIcon } from "./specStudioIconPaths";
import { StudioIcon } from "./specStudioIcons";
import type { Artefact, Block, DataView, Device, Screen } from "./specStudioModel";

// The product's screen as the spec describes it, drawn only from the spec's tokens (`--m-*`, set by the frame).
// Not Octryx UI: the root carries data-ds-audit="skip" so the UI audit measures the Studio around it, never the
// product's own type and radius. Every element a comment may name carries data-mock-path and
// data-mock-name; nothing here is a real control (the mock only shows, the comment mode and "go" links act).

type Props = {
  artefact: Pick<Artefact, "nav" | "title">;
  screen: Screen;
  device: Device;
  data: DataView;
  onGo?: (screenId: string) => void;
};

function tone(value: string | undefined): string {
  return value && ["ok", "warn", "error", "accent", "neutral"].includes(value) ? value : "neutral";
}

function Mark({ path, name, className, children, style }: { path: string; name: string; className: string;
  children?: ReactNode; style?: CSSProperties }) {
  return <div className={className} data-mock-path={path} data-mock-name={name} style={style}>{children}</div>;
}

function Icon({ name, size = 20 }: { name?: string; size?: number }) {
  const { icons } = useContext(MockAssetsContext);
  const [broken, setBroken] = useState(false);
  const url = name ? icons[name] : undefined;
  // A CI icon of the same name replaces the line icon; one that does not load falls back quietly.
  if (url && !broken) return <img className="mk-ci-icon" src={url} width={size} height={size} alt="" onError={() => setBroken(true)} />;
  return isStudioIcon(name) ? <StudioIcon name={name} size={size} /> : null;
}

function Brand({ title }: { title: string }) {
  const { logo } = useContext(MockAssetsContext);
  const [broken, setBroken] = useState(false);
  if (logo && !broken) return <div className="mk-brand"><img className="mk-brand__logo" src={logo} alt={title} onError={() => setBroken(true)} /></div>;
  return <div className="mk-brand">{title}</div>;
}

function BlockView({ block, path, onGo }: { block: Block; path: string; onGo?: (id: string) => void }): ReactNode {
  const text = block.text ?? "";
  switch (block.type) {
    case "eyebrow": return <Mark path={path} name={text} className="mk-eyebrow-x">{text}</Mark>;
    case "title": return <Mark path={path} name={text} className="mk-h1">{text}</Mark>;
    case "text": return <Mark path={path} name={text} className="mk-text">{text}</Mark>;
    case "muted": return <Mark path={path} name={text} className="mk-text mk-muted">{text}</Mark>;
    case "card": return (
      <Mark path={path} name={block.title || "Card"} className="mk-card">
        {block.title ? <div className="mk-h2">{block.title}</div> : null}
        {(block.blocks ?? []).map((child, i) => <BlockView key={i} block={child} path={`${path}.${i}`} onGo={onGo} />)}
      </Mark>);
    case "row": return (
      <Mark path={path} name="Row" className="mk-row">
        {(block.blocks ?? []).map((child, i) => <BlockView key={i} block={child} path={`${path}.${i}`} onGo={onGo} />)}
      </Mark>);
    case "item": return (
      <Mark path={path} name={block.title || "Item"} className="mk-item">
        <div className="mk-art">{block.icon ? <Icon name={block.icon} size={24} /> : null}<span>{block.icon ? "" : block.art}</span></div>
        <div className="mk-item__body">
          <div className="mk-h2">{block.title}</div>
          {block.meta ? <div className="mk-muted mk-small">{block.meta}</div> : null}
          {block.badge ? <span className={`mk-chip mk-tone-${tone(block.badge_tone)}`}>{block.badge}</span> : null}
        </div>
        {block.icon && block.art ? <span className="mk-num mk-muted">{block.art}</span> : null}
      </Mark>);
    case "button": return (
      <Mark path={path} name={text || "Button"} className={`mk-btn${block.variant === "secondary" ? " mk-btn--secondary" : ""}`}>
        <span onClick={block.go && onGo ? () => onGo(block.go as string) : undefined}>{text}</span>
      </Mark>);
    case "field": return (
      <Mark path={path} name={block.label || "Field"} className="mk-field">
        <span className="mk-muted mk-small">{block.label}</span>
        <span className="mk-input"><span className="mk-num">{String(block.value ?? "")}</span>{block.suffix ? <span className="mk-muted">{block.suffix}</span> : null}</span>
      </Mark>);
    case "chips": return (
      <Mark path={path} name="Chips" className="mk-chips">
        {(block.items ?? []).map((item, i) => <span key={i} className={`mk-chip mk-tone-${tone(item.tone)}`} data-mock-path={`${path}.${i}`} data-mock-name={item.text}>{item.text}</span>)}
      </Mark>);
    case "banner": return (
      <Mark path={path} name={text} className={`mk-banner mk-tone-${tone(block.tone)}`}>
        <Icon name="warning" size={18} /><span>{text}</span>{block.action ? <strong className="mk-banner__action">{block.action}</strong> : null}
      </Mark>);
    case "progress": return (
      <Mark path={path} name={block.label || "Progress"} className="mk-progress">
        <div className="mk-bar"><i style={{ width: `${Math.round(Number(block.value ?? 0) * 100)}%` }} /></div>
        {block.label ? <span className="mk-muted mk-small">{block.label}</span> : null}
      </Mark>);
    case "big": return (
      <Mark path={path} name={text} className="mk-big">
        <div className="mk-num mk-big__value">{text}</div>{block.sub ? <div className="mk-big__sub">{block.sub}</div> : null}
      </Mark>);
    case "kpis": return (
      <Mark path={path} name="Figures" className="mk-kpis">
        {(block.items ?? []).map((item, i) => (
          <div key={i} className="mk-kpi" data-mock-path={`${path}.${i}`} data-mock-name={item.label}>
            <span className="mk-num mk-kpi__value">{item.value}</span><span className="mk-muted mk-small">{item.label}</span>
          </div>))}
      </Mark>);
    case "empty": return (
      <Mark path={path} name={block.title || "Empty state"} className="mk-empty">
        <Icon name={block.icon} size={48} /><div className="mk-h2">{block.title}</div>
        <div className="mk-muted">{block.text}</div>{block.action ? <span className="mk-btn">{block.action}</span> : null}
      </Mark>);
    case "image": return (
      <Mark path={path} name={block.label || "Image"} className="mk-image"><Icon name={block.icon || "image"} size={28} /><span className="mk-small">{block.label}</span></Mark>);
    default: return null;
  }
}

export function MockScreen({ artefact, screen, device, data, onGo }: Props) {
  const phone = device === "phone";
  const nav = artefact.nav.filter((entry) => (phone ? entry.phone !== false : entry.id !== "more"));
  const blocks = data === "empty" && screen.empty.length ? screen.empty : screen.filled;
  const navBar = screen.focus || !nav.length ? null : (
    <nav className="mk-nav">
      {!phone ? <Brand title={artefact.title} /> : null}
      {nav.map((entry) => (
        <div key={entry.id} className={`mk-nav__item${entry.id === screen.nav ? " is-on" : ""}`}
          data-mock-path={`nav.${entry.id}`} data-mock-name={entry.label}>
          <Icon name={entry.icon} size={phone ? 22 : 18} /><span>{entry.label}</span>
        </div>
      ))}
    </nav>
  );
  return (
    <div className={`mk-app mk-app--${device}${screen.focus ? " mk-app--focus" : ""}`}>
      {phone ? null : navBar}
      <main className="mk-main">
        {data === "empty" && !screen.empty.length && screen.empty_not_applicable ? (
          <div className="mk-muted mk-note">{screen.empty_not_applicable}</div>
        ) : null}
        {blocks.map((block, i) => <BlockView key={`${data}-${i}`} block={block} path={`${data}.${i}`} onGo={onGo} />)}
      </main>
      {phone ? navBar : null}
    </div>
  );
}
