import { useEffect, useRef, useState, type MutableRefObject } from "react";

import { ChoiceGroup } from "../../layout/ChoiceGroup";
import { ColorRow } from "../../layout/ColorRow";
import { StatusLabel } from "../../layout/StatusLabel";
import { MockFrame, type PinTarget } from "./MockFrame";
import { elementCentre } from "./specStudioDom";
import { SaveLine } from "./SaveLine";
import { StudioIcon } from "./specStudioIcons";
import {
  contrastRows, corporateAssetUrl, directionsOf, effectiveDesign, isContextScreen, mockElements, RADIUS_MAX, screensOf,
  validRadius, valueMark, type DataView, type Device, type StudioPayload, type Theme,
} from "./specStudioModel";
import { CommentList, Deviations } from "./StudioDesignNotes";
import type { SpecStudioHandle } from "./useSpecStudio";

// Design: pick a direction, change colours, font and radius, and see the real screens change at once — light/dark,
// desktop/phone, empty/with data (prototype v3, approved). The contrast check blocks approval.

const COLOR_NAMES: [string, string][] = [
  ["bg", "Background"], ["surface", "Cards"], ["text", "Text"], ["muted", "Muted text"], ["accent", "Main action"],
  ["ok", "OK"], ["warn", "Warning"], ["error", "Error"],
];

const SOURCE_LABEL = { ci: "Corporate", derived: "derived", differs: "differs from Corporate" } as const;

type Design = ReturnType<typeof effectiveDesign>;
type Change = Record<string, unknown> & { op: string };
type Screen = ReturnType<typeof screensOf>[number];

// The view choices of the design stage; they stay here so a change of screen or device keeps the others.
function useDesignView(payload: StudioPayload, screens: Screen[]) {
  const { artefact } = payload;
  const [screenId, setScreenId] = useState(screens[0]?.id ?? "");
  const [device, setDevice] = useState<Device>(artefact.target === "flutter" ? "phone" : "desktop");
  const [theme, setTheme] = useState<Theme>("light");
  const [data, setData] = useState<DataView>("filled");
  const [zoom, setZoom] = useState(false);
  const [commenting, setCommenting] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [radius, setRadius] = useState(String(payload.design.radius));
  const stage = useRef<HTMLDivElement | null>(null);
  useEffect(() => setRadius(String(payload.design.radius)), [payload.design.radius]);
  return { screenId, setScreenId, device, setDevice, theme, setTheme, data, setData, zoom, setZoom, commenting, setCommenting,
    selected, setSelected, radius, setRadius, stage };
}

type DesignView = ReturnType<typeof useDesignView>;

// Where each value comes from (Corporate, derived, differs) and whether the Corporate Identity locks it.
function valueMarks(payload: StudioPayload, design: Design) {
  const corporate = payload.corporate ?? null;
  const lockOf = (path: string) => (valueMark(payload, design, path).locked
    ? { icon: <StudioIcon name="lock" size={14} />, reason: `Locked by the Corporate Identity ${corporate?.profile_name ?? ""}` }
    : null);
  const sourceOf = (path: string) => {
    const source = valueMark(payload, design, path).source;
    if (source === "ci" && (payload.deviations ?? []).some((d) => d.path === path)) return SOURCE_LABEL.differs;
    return source ? SOURCE_LABEL[source] : null;
  };
  return { lockOf, sourceOf };
}

function corporateAssets(payload: StudioPayload, design: Design) {
  const corporate = payload.corporate ?? null;
  return corporate && design.direction === "corporate" ? {
    logo: corporate.logo ? corporateAssetUrl(payload.run_id, corporate.logo) : undefined,
    icons: Object.fromEntries(Object.entries(corporate.icons).map(([slug, path]) => [slug, corporateAssetUrl(payload.run_id, path)])),
  } : undefined;
}

export function StudioDesign({ payload, studio }: { payload: StudioPayload; studio: SpecStudioHandle }) {
  const { artefact, state } = payload;
  const screens = screensOf(payload);
  const view = useDesignView(payload, screens);
  const { screenId, device, theme, data, setSelected, radius } = view;

  const design = effectiveDesign(artefact, state, payload.design, payload.corporate);
  const screen = screens.find((item) => item.id === screenId) ?? screens[0];
  const save = (change: Change) => void studio.save("design", change);
  const saveComment = (change: Change) => studio.save("comments", change);

  const pin = async (target: PinTarget) => {
    const next = await saveComment({ op: "comment.add", screen: screen.id, device, theme, data, x: target.x, y: target.y,
      element: target.element, path: target.path, text: "" });
    const added = next?.state.comments?.at(-1);
    if (added) setSelected(added.id);
  };
  const addFromList = (path: string) => {
    const element = mockElements(artefact, screen, device, data).find((item) => item.path === path);
    const centre = elementCentre(view.stage.current, path) ?? { x: 24, y: 24 };
    if (element) void pin({ ...centre, path, element: element.name });
  };
  const radiusValue = validRadius(radius);
  const commitRadius = () => { if (radiusValue !== null && radiusValue !== payload.design.radius) save({ op: "design", radius: radiusValue }); };

  if (!screen) return null;
  return (
    <div className="studio-design">
      <DesignControls payload={payload} studio={studio} design={design} view={view} save={save} radiusValue={radiusValue}
        commitRadius={commitRadius} />
      <DesignStage payload={payload} studio={studio} design={design} view={view} screens={screens} screen={screen}
        stage={view.stage} pin={pin} addFromList={addFromList} />
    </div>
  );
}

function DesignControls({ payload, studio, design, view, save, radiusValue, commitRadius }: {
  payload: StudioPayload; studio: SpecStudioHandle; design: Design; view: DesignView; save: (change: Change) => void;
  radiusValue: number | null; commitRadius: () => void;
}) {
  const { theme, radius, setRadius } = view;
  const directions = directionsOf(payload.artefact, payload.corporate);
  const corporate = payload.corporate ?? null;
  const { lockOf, sourceOf } = valueMarks(payload, design);
  const frozen = payload.frozen;
  const rows = contrastRows(design);
  return (
    <div className="studio-controls">
      {directions.length ? (
        <div className="studio-control">
          <span className="studio-label">Style direction</span>
          <ChoiceGroup label="Style direction" value={design.direction} onChange={(key) => save({ op: "design", direction: key })}
            choices={directions.map((d) => ({ key: d.id, label: d.name, disabled: frozen || (Boolean(corporate?.locks.length) && d.id !== "corporate") }))} />
          <span className="studio-hint">{directions.find((d) => d.id === design.direction)?.hint}</span>
        </div>
      ) : <p className="studio-hint">This feature uses the approved app's design; change it in the app's own Studio.</p>}
      <div className="studio-control">
        <span className="studio-label">Colours ({theme === "light" ? "light" : "dark"} theme)</span>
        <div className="studio-colors">
          {COLOR_NAMES.filter(([key]) => design[theme][key]).map(([key, label]) => (
            <ColorRow key={`${theme}-${key}`} name={key} label={label} value={design[theme][key]} disabled={frozen}
              source={sourceOf(`${theme}.${key}`)} locked={lockOf(`${theme}.${key}`)}
              onSave={(hex) => save({ op: "design", theme, key, value: hex })} />
          ))}
        </div>
      </div>
      <div className="studio-control">
        <span className="studio-label">Fonts</span>
        <span className="studio-hint">{design.fonts.head.split(",")[0]} for headings, {design.fonts.body.split(",")[0]} for text. The preview uses the fonts installed here, else a fallback.</span>
      </div>
      <Deviations payload={payload} studio={studio} />
      <div className="studio-control">
        <label className="studio-label" htmlFor="studio-radius">Corners</label>
        <div className="studio-radius">
          <input id="studio-radius" type="range" className="studio-range" min={0} max={RADIUS_MAX} step={1}
            value={radiusValue ?? payload.design.radius} disabled={frozen}
            onChange={(event) => setRadius(event.target.value)} onPointerUp={commitRadius} onKeyUp={commitRadius} />
          <input type="number" className="admin-panel__input ds-input studio-radius__value" min={0} max={RADIUS_MAX} value={radius}
            disabled={frozen} aria-label="Corner radius in px" aria-invalid={radiusValue === null}
            onChange={(event) => setRadius(event.target.value)} onBlur={commitRadius} />
          <span className="studio-hint">px</span>
        </div>
      </div>
      <ContrastCheck rows={rows} theme={theme} />
      <SaveLine save={studio.saves.design} />
    </div>
  );
}

function ContrastCheck({ rows, theme }: { rows: ReturnType<typeof contrastRows>; theme: Theme }) {
  return (
    <div className="studio-control">
      <span className="studio-label">Contrast (WCAG AA, 4.5 : 1)</span>
      <ul className="studio-contrast">
        {rows.filter((row) => row.theme === theme).map((row) => (
          <li key={row.pair}>
            <StatusLabel tone={row.passes ? "success" : "problem"} label={row.passes ? "Passes" : "Too weak"} />
            <span>{row.pair}: {row.ratio.toFixed(1)} : 1</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function StageBar({ payload, screens, screen, view }: { payload: StudioPayload; screens: Screen[]; screen: Screen; view: DesignView }) {
  const { device, setDevice, theme, setTheme, data, setData, zoom, setZoom, commenting, setCommenting, setScreenId } = view;
  return (
    <div className="studio-stagebar">
      <ChoiceGroup label="Screen" value={screen.id} onChange={setScreenId}
        choices={screens.map((s) => ({ key: s.id, label: isContextScreen(payload, s.id) ? `${s.name} (existing)` : s.name }))} />
      <ChoiceGroup label="Device" value={device} onChange={(key) => setDevice(key as Device)} choices={[
        { key: "desktop", label: "Desktop", icon: <StudioIcon name="desktop" /> },
        { key: "phone", label: "Phone", icon: <StudioIcon name="phone" /> }]} />
      <ChoiceGroup label="Theme" value={theme} onChange={(key) => setTheme(key as Theme)} choices={[
        { key: "light", label: "Light", icon: <StudioIcon name="sun" /> },
        { key: "dark", label: "Dark", icon: <StudioIcon name="moon" /> }]} />
      <ChoiceGroup label="Data" value={data} onChange={(key) => setData(key as DataView)} choices={[
        { key: "filled", label: "With data" }, { key: "empty", label: "Empty" }]} />
      <button type="button" className="ds-btn ds-btn--sm studio-tool" aria-pressed={zoom} onClick={() => setZoom(!zoom)}>
        <StudioIcon name={zoom ? "fit" : "zoom"} />{zoom ? "Fit to width" : "100 %"}
      </button>
      <button type="button" className="ds-btn ds-btn--sm studio-tool" aria-pressed={commenting} disabled={payload.frozen}
        onClick={() => setCommenting(!commenting)}>
        <StudioIcon name="comment" />{commenting ? "Stop commenting" : "Comment"}
      </button>
    </div>
  );
}

function DesignStage({ payload, studio, design, view, screens, screen, stage, pin, addFromList }: {
  payload: StudioPayload; studio: SpecStudioHandle; design: Design; view: DesignView; screens: Screen[]; screen: Screen;
  stage: MutableRefObject<HTMLDivElement | null>; pin: (target: PinTarget) => Promise<void>; addFromList: (path: string) => void;
}) {
  const { artefact } = payload;
  const { device, setDevice, theme, data, zoom, commenting, selected, setSelected, setScreenId } = view;
  const comments = payload.state.comments ?? [];
  return (
    <div className="studio-stage" ref={stage}>
      <StageBar payload={payload} screens={screens} screen={screen} view={view} />
      {commenting ? <p className="studio-banner" role="status">Comment mode: tap the place in the mock you mean, then write what should change below.</p> : null}
      <MockFrame artefact={{ nav: artefact.nav.length ? artefact.nav : payload.base?.nav ?? [], title: artefact.title }}
        assets={corporateAssets(payload, design)}
        screen={screen} device={device} theme={theme} data={data} design={design} zoom={zoom} commenting={commenting}
        comments={comments} selected={selected} onPin={(target) => void pin(target)}
        onSelectComment={setSelected} onGo={(id) => { if (screens.some((s) => s.id === id)) setScreenId(id); }} />
      <p className="studio-hint">{screen.note || `Next step: ${screen.next_step}`}</p>
      <CommentList payload={payload} studio={studio} selected={selected} onSelect={(id) => {
        const comment = comments.find((c) => c.id === id);
        setSelected(id);
        if (comment) { setScreenId(comment.screen); setDevice(comment.device); }
      }} elements={mockElements(artefact, screen, device, data)} onAdd={addFromList} />
    </div>
  );
}
