// The turn's options of one chat (model, effort, permission mode), kept on this phone per chat; a new chat starts
// with the last model and effort, and always with "Ask first".

import { useState } from "react";
import { initialTurnOptions, turnOptionsToStore, type TurnOptions } from "./mobileTurnOptions";

export function useTurnOptions(threadId: string | null) {
  const [options, setOptions] = useState<TurnOptions>(() => {
    try {
      return initialTurnOptions(threadId, (key) =>
        window.localStorage.getItem(key),
      );
    } catch {
      return initialTurnOptions(threadId, () => null);
    }
  });
  const update = (patch: Partial<TurnOptions>) => {
    const next = { ...options, ...patch };
    setOptions(next);
    try {
      for (const [key, value] of turnOptionsToStore(threadId, next))
        window.localStorage.setItem(key, value);
    } catch {
      // private mode: the choice lasts for this screen
    }
  };
  return [options, update] as const;
}
