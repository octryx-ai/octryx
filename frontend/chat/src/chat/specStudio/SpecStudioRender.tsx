import { type CSSProperties, useEffect, useState } from "react";

import { loadStudio } from "./specStudioApi";
import type { SpecStudioAddress } from "./specStudioAddress";
import { MockScreen } from "./MockScreen";
import { MOCK_WIDTH, mockVariables, screensOf, type EffectiveDesign, type StudioPayload } from "./specStudioModel";
import "./spec-studio.css";

// One screen of the approved mock, nothing around it: the baseline image hands_on and the story review take.
// Still behind the login: the app shell only renders it after the bootstrap.

export function SpecStudioRender({ address }: { address: SpecStudioAddress }) {
  const [payload, setPayload] = useState<StudioPayload | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    loadStudio(address.runId).then(setPayload).catch((reason) => setError(String(reason?.message ?? reason)));
  }, [address.runId]);
  const render = address.render;
  if (!render) return null;
  if (error) return <p className="ds-empty" role="alert">{error}</p>;
  if (!payload) return null;
  const approved = render.version ? payload.approved.find((item) => item.version === render.version) : null;
  const design: EffectiveDesign = approved?.design ?? payload.design;
  const screen = screensOf(payload).find((item) => item.id === render.screen);
  if (!screen) return <p className="ds-empty" role="alert">No such screen.</p>;
  return (
    <div className="studio-render" data-testid="spec-studio-render" style={{ width: MOCK_WIDTH[render.device] }}>
      <div className={`studio-frame studio-frame--${render.device}`} data-ds-audit="skip"
        style={mockVariables(design, render.theme) as CSSProperties}>
        <MockScreen artefact={{ nav: payload.artefact.nav.length ? payload.artefact.nav : payload.base?.nav ?? [], title: payload.artefact.title }}
          screen={screen} device={render.device} data={render.data} />
      </div>
    </div>
  );
}
