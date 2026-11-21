import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type MouseEvent } from "react";

import { MockAssetsContext, type MockAssets } from "./mockAssets";
import { MockScreen } from "./MockScreen";
import {
  describeElement, MOCK_WIDTH, mockScale, mockVariables, pinPosition,
  type Artefact, type Comment, type DataView, type Device, type EffectiveDesign, type Screen, type Theme,
} from "./specStudioModel";

// The live mock at its real width (1280 desktop, 390 phone), scaled down to the space there is: a phone sees the
// WHOLE desktop mock, "100 %" shows it unscaled and the stage scrolls sideways inside itself only.
// In comment mode a tap on an element pins a numbered note there (stored in the mock's own pixels, so it stays put
// at any scale); the pins are real buttons, so they are reachable by keyboard.

export type PinTarget = { x: number; y: number; path: string; element: string };

type Props = {
  artefact: Pick<Artefact, "nav" | "title">;
  screen: Screen;
  device: Device;
  theme: Theme;
  data: DataView;
  design: EffectiveDesign;
  zoom: boolean;
  commenting: boolean;
  comments: Comment[];
  selected: string | null;
  onPin: (target: PinTarget) => void;
  onSelectComment: (id: string) => void;
  onGo: (screenId: string) => void;
  // The Corporate Identity's logo and icons, when the corporate direction is in use.
  assets?: MockAssets;
};

const NO_ASSETS: MockAssets = { icons: {} };

export function MockFrame({ artefact, screen, device, theme, data, design, zoom, commenting, comments, selected, onPin,
  onSelectComment, onGo, assets = NO_ASSETS }: Props) {
  const viewport = useRef<HTMLDivElement | null>(null);
  const scaler = useRef<HTMLDivElement | null>(null);
  const [scale, setScale] = useState(1);
  const [height, setHeight] = useState(0);

  useLayoutEffect(() => {
    const measure = () => {
      const available = viewport.current?.clientWidth ?? 0;
      const next = mockScale(available, device, zoom);
      setScale(next);
      setHeight(Math.ceil((scaler.current?.offsetHeight ?? 0) * next));
    };
    measure();
    if (typeof ResizeObserver === "undefined" || !viewport.current) return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(viewport.current);
    if (scaler.current) observer.observe(scaler.current);
    return () => observer.disconnect();
  }, [device, zoom, screen.id, data]);

  useEffect(() => {
    if (!zoom && viewport.current) viewport.current.scrollLeft = 0;
  }, [zoom]);

  const capture = (event: MouseEvent<HTMLDivElement>) => {
    if (!commenting || !scaler.current) return;
    event.preventDefault();
    event.stopPropagation();
    const target = (event.target as HTMLElement).closest("[data-mock-path]") as HTMLElement | null;
    const box = scaler.current.getBoundingClientRect();
    const { x, y } = pinPosition(event.clientX, event.clientY, box, scale);
    onPin({ x, y, path: target?.dataset.mockPath ?? "", element: describeElement(target?.dataset.mockName ?? "", screen.name) });
  };

  const variables = mockVariables(design, theme) as CSSProperties;
  const visible = comments.filter((c) => c.screen === screen.id && c.device === device);
  const width = MOCK_WIDTH[device];
  return (
    <div ref={viewport} className={`studio-viewport${zoom ? " is-zoomed" : ""}`} style={{ height: height || undefined }}
      data-testid="studio-viewport">
      <div ref={scaler} className="studio-scaler" style={{ width, transform: `scale(${scale})` }}>
        <div className={`studio-frame studio-frame--${device}${commenting ? " is-commenting" : ""}`} onClickCapture={capture}
          data-ds-audit="skip" data-testid="studio-mock" style={variables}>
          <MockAssetsContext.Provider value={assets}>
            <MockScreen artefact={artefact} screen={screen} device={device} data={data} onGo={onGo} />
          </MockAssetsContext.Provider>
        </div>
        <div className="studio-pins">
          {visible.map((comment) => {
            const number = comments.indexOf(comment) + 1;
            return (
              <button key={comment.id} type="button" className={`studio-pin${comment.id === selected ? " is-selected" : ""}`}
                style={{ left: comment.x, top: comment.y, transform: `scale(${1 / scale})` }}
                aria-label={`Note ${number} at ${comment.element || screen.name}`}
                onClick={() => onSelectComment(comment.id)}>{number}</button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
