import { useEffect, useState } from "react";

import { ChoiceGroup } from "../../layout/ChoiceGroup";
import { SaveLine } from "./SaveLine";
import { StudioIcon } from "./specStudioIcons";
import type { StudioPayload } from "./specStudioModel";
import type { SpecStudioHandle } from "./useSpecStudio";

// The acceptance criteria every story is measured against: OK, or Change with a note (sent back on revision).

function CriterionRow({ id, text, payload, studio }: { id: string; text: string; payload: StudioPayload; studio: SpecStudioHandle }) {
  const verdict = payload.state.acceptance?.[id];
  const [note, setNote] = useState(verdict?.note ?? "");
  useEffect(() => setNote(verdict?.note ?? ""), [verdict?.note]);
  const key = `ac:${id}`;
  const change = verdict?.verdict === "change";
  return (
    <div className="studio-ac">
      <code className="studio-code">{id}</code>
      <span className="studio-ac__text">{text}</span>
      <ChoiceGroup label={`${id} verdict`} value={change ? "change" : "ok"}
        onChange={(value) => void studio.save("acceptance", { op: "acceptance", id, verdict: value, note })}
        choices={[{ key: "ok", label: "OK", icon: <StudioIcon name="check" />, disabled: payload.frozen },
          { key: "change", label: "Change", icon: <StudioIcon name="x" />, disabled: payload.frozen }]} />
      {change ? (
        <input type="text" className="admin-panel__input ds-input studio-ac__note" value={note} disabled={payload.frozen}
          placeholder="What should it say instead?" aria-label={`What ${id} should say instead`}
          onChange={(event) => { setNote(event.target.value); studio.markDirty(key, event.target.value !== (verdict?.note ?? "")); }}
          onBlur={() => { studio.markDirty(key, false); if (note !== (verdict?.note ?? "")) void studio.save("acceptance", { op: "acceptance", id, verdict: "change", note }); }} />
      ) : null}
    </div>
  );
}

export function StudioAcceptance({ payload, studio }: { payload: StudioPayload; studio: SpecStudioHandle }) {
  return (
    <div className="studio-stack">
      {payload.artefact.acceptance.map((item) => (
        <CriterionRow key={item.id} id={item.id} text={item.text} payload={payload} studio={studio} />
      ))}
      <SaveLine save={studio.saves.acceptance} />
    </div>
  );
}
