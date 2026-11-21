// The live session's composer actions: attach pictures (made smaller) and send the message with them.

import type { Dispatch, MutableRefObject, SetStateAction } from "react";
import { sendLive } from "./mobileApi";
import { type MobileError } from "./mobileSession";
import type { LiveSession } from "./mobileLiveSessions";
import { MAX_PICTURES, shrinkPicture } from "./pictures";
import { REFUSALS, type Picture } from "./liveSessionText";

export function liveComposeActions({ session, draft, setDraft, busy, setBusy, pictures, setPictures, setError, picker,
  refresh }: {
  session: LiveSession;
  draft: string;
  setDraft: (draft: string) => void;
  busy: boolean;
  setBusy: (busy: boolean) => void;
  pictures: Picture[];
  setPictures: Dispatch<SetStateAction<Picture[]>>;
  setError: (error: string) => void;
  picker: MutableRefObject<HTMLInputElement | null>;
  refresh: () => Promise<void>;
}) {
  const attach = async (files: FileList | null) => {
    const chosen = Array.from(files ?? []).slice(
      0,
      MAX_PICTURES - pictures.length,
    );
    setError("");
    for (const file of chosen) {
      try {
        const data = await shrinkPicture(file);
        setPictures((current) =>
          current.length >= MAX_PICTURES
            ? current
            : [
                ...current,
                {
                  key: `${file.name}-${current.length}-${Date.now()}`,
                  preview: `data:image/jpeg;base64,${data}`,
                  data,
                },
              ],
        );
      } catch (reason) {
        setError(
          REFUSALS[(reason as Error).message] ??
            "This picture could not be attached.",
        );
      }
    }
    if (picker.current) picker.current.value = "";
  };

  const submit = async () => {
    const text = draft.trim();
    if ((!text && pictures.length === 0) || busy) return;
    setBusy(true);
    setError("");
    try {
      await sendLive(
        session.deviceId,
        session.peer,
        text,
        pictures.map((picture) => picture.data),
      );
      setDraft("");
      setPictures([]);
      await refresh();
    } catch (reason) {
      const code = (reason as MobileError).code ?? "";
      setError(
        REFUSALS[code] ??
          (code ? code.replace(/_/g, " ") : "The message was not sent."),
      );
    } finally {
      setBusy(false);
    }
  };
  return { attach, submit };
}
