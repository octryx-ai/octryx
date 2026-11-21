import { useState } from "react";

import { canRemoveSeatModel, seatModelProblem, withSeatModel, withoutSeatModel } from "./seatPolicyModel";
import type { SeatModelLimits } from "./seatPolicyModel";

// The model id list of a seat (Claude `seat_models`, Codex `codex_seat_models`): the ids, Remove per id and an Add
// field with the backend limits checked at the field. `onSave` writes the whole new list and says whether it worked.
export function SeatModelListEditor({ testId, models, limits, canRemove, canAdd, locked, saving, placeholder, onSave }: {
  testId: string;
  models: string[];
  limits: SeatModelLimits;
  canRemove: boolean;
  canAdd: boolean;
  locked: boolean;
  saving: boolean;
  placeholder: string;
  onSave: (models: string[]) => Promise<boolean>;
}) {
  const [candidate, setCandidate] = useState("");
  const [tried, setTried] = useState(false);
  const problem = candidate || tried ? seatModelProblem(candidate, models, limits) : null;
  const problemId = `${testId}-problem`;

  const addModel = async () => {
    setTried(true);
    if (seatModelProblem(candidate, models, limits)) return;
    if (await onSave(withSeatModel(models, candidate))) { setCandidate(""); setTried(false); }
  };

  return (
    <>
      <ul className="seat-models__list" data-testid={`${testId}-list`}>
        {models.map((item) => (
          <li key={item} className="seat-models__item">
            <code className="seat-models__id">{item}</code>
            {canRemove ? (
              <button type="button" className="admin-panel__action-btn" aria-label={`Remove ${item}`}
                disabled={locked || !canRemoveSeatModel(models)}
                title={canRemoveSeatModel(models) ? undefined : "The list keeps at least one model."}
                onClick={() => void onSave(withoutSeatModel(models, item))}>Remove</button>
            ) : null}
          </li>
        ))}
      </ul>
      {canAdd ? (
        <>
          <div className="seat-models__add">
            <input type="text" className="admin-panel__input seat-models__input" data-testid={`${testId}-input`}
              aria-label="Model id to add" placeholder={placeholder} value={candidate}
              maxLength={limits.maxModelIdChars} disabled={locked} aria-invalid={problem ? true : undefined}
              aria-describedby={problem ? problemId : undefined}
              onChange={(event) => setCandidate(event.target.value)}
              onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); void addModel(); } }} />
            <button type="button" className="admin-panel__action-btn" data-testid={`${testId}-add`}
              disabled={locked || Boolean(candidate && problem)} onClick={() => void addModel()}>
              {saving ? "Saving…" : "Add model"}
            </button>
          </div>
          {problem ? <p className="seat-models__problem" id={problemId} role="alert" data-testid={`${testId}-problem`}>{problem}</p> : (
            <p className="admin-panel__hint">{models.length} of {limits.maxModels} models; at least one stays in the list.</p>
          )}
        </>
      ) : null}
    </>
  );
}
