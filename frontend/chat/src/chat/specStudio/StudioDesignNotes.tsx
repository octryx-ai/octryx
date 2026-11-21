// The notes under the Spec Studio design stage and the reasons for each change of the company's look.
import { useEffect, useRef, useState } from "react";

import { lockLabel } from "../../admin/components/corpIdentity/corpStudioLocksModel";
import { SaveLine } from "./SaveLine";
import { StudioIcon } from "./specStudioIcons";
import { screensOf, type StudioPayload } from "./specStudioModel";
import type { SpecStudioHandle } from "./useSpecStudio";

export function CommentList({ payload, studio, selected, onSelect, elements, onAdd }: { payload: StudioPayload;
  studio: SpecStudioHandle; selected: string | null; onSelect: (id: string) => void;
  elements: { path: string; name: string }[]; onAdd: (path: string) => void }) {
  const comments = payload.state.comments ?? [];
  const names = Object.fromEntries(screensOf(payload).map((s) => [s.id, s.name]));
  return (
    <div className="studio-comments">
      {!payload.frozen ? (
        <label className="studio-comments__add">
          <span className="studio-label">Add a note to an element</span>
          <select className="admin-users__toolbar-select ds-input" value="" onChange={(event) => { if (event.target.value) onAdd(event.target.value); }}>
            <option value="">Choose an element…</option>
            {elements.map((item) => <option key={item.path} value={item.path}>{item.name}</option>)}
          </select>
        </label>
      ) : null}
      {comments.map((comment, index) => (
        <CommentRow key={comment.id} number={index + 1} comment={comment} screenName={names[comment.screen] ?? comment.screen}
          selected={comment.id === selected} frozen={payload.frozen} studio={studio} onSelect={() => onSelect(comment.id)} />
      ))}
      <SaveLine save={studio.saves.comments} />
    </div>
  );
}

function CommentRow({ number, comment, screenName, selected, frozen, studio, onSelect }: { number: number;
  comment: NonNullable<StudioPayload["state"]["comments"]>[number]; screenName: string; selected: boolean; frozen: boolean;
  studio: SpecStudioHandle; onSelect: () => void }) {
  const [text, setText] = useState(comment.text);
  const textarea = useRef<HTMLTextAreaElement | null>(null);
  useEffect(() => setText(comment.text), [comment.text]);
  useEffect(() => { if (selected && !comment.text) textarea.current?.focus(); }, [selected, comment.text]);
  const key = `comment:${comment.id}`;
  const send = () => {
    studio.markDirty(key, false);
    if (text.trim() !== comment.text) void studio.save("comments", { op: "comment.edit", id: comment.id, text });
  };
  return (
    <div className={`ds-card studio-comment${selected ? " is-selected" : ""}`}>
      <span className="studio-comment__number" aria-hidden="true">{number}</span>
      <div className="studio-comment__body">
        <span className="ds-card__meta">{screenName} · {comment.device === "phone" ? "Phone" : "Desktop"} · at “{comment.element}”</span>
        <textarea ref={textarea} className="admin-panel__textarea" rows={2} value={text} disabled={frozen}
          aria-label={`Note ${number}`} placeholder="For example: icons, not names" onFocus={onSelect}
          onChange={(event) => { setText(event.target.value); studio.markDirty(key, event.target.value !== comment.text); }}
          onBlur={send} />
      </div>
      {!frozen ? (
        <button type="button" className="ds-btn ds-btn--ghost ds-btn--sm" aria-label={`Delete note ${number}`}
          onClick={() => void studio.save("comments", { op: "comment.remove", id: comment.id })}>
          <StudioIcon name="x" />
        </button>
      ) : null}
    </div>
  );
}

/** What the spec changes of the company's look, each with the reason that goes into SPEC.md. */
export function Deviations({ payload, studio }: { payload: StudioPayload; studio: SpecStudioHandle }) {
  const deviations = payload.deviations ?? [];
  if (!payload.corporate || !deviations.length) return null;
  return (
    <div className="studio-control">
      <span className="studio-label">Differs from Corporate: {payload.corporate.profile_name}</span>
      <ul className="studio-deviations">
        {deviations.map((deviation) => (
          <ReasonRow key={deviation.path} deviation={deviation} frozen={payload.frozen} studio={studio} />
        ))}
      </ul>
    </div>
  );
}

function ReasonRow({ deviation, frozen, studio }: { deviation: NonNullable<StudioPayload["deviations"]>[number];
  frozen: boolean; studio: SpecStudioHandle }) {
  const [text, setText] = useState(deviation.reason);
  useEffect(() => setText(deviation.reason), [deviation.reason]);
  const key = `reason:${deviation.path}`;
  const send = () => {
    studio.markDirty(key, false);
    if (text.trim() !== deviation.reason) void studio.save("design", { op: "reason", path: deviation.path, text: text.trim() });
  };
  const what = lockLabel(deviation.path);
  return (
    <li className="studio-deviation">
      <span className="studio-deviation__diff">
        {what}: {deviation.chosen} instead of {deviation.corporate}
      </span>
      <input type="text" className="admin-panel__input ds-input" value={text} disabled={frozen} maxLength={1000}
        aria-label={`Reason: ${what} differs from Corporate`} placeholder="Why does the spec differ?"
        onChange={(event) => { setText(event.target.value); studio.markDirty(key, event.target.value !== deviation.reason); }}
        onBlur={send} onKeyDown={(event) => { if (event.key === "Enter") send(); }} />
    </li>
  );
}
