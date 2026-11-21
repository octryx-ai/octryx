import { useEffect, useRef, useState, type MutableRefObject } from "react";

type ReadJsonFn = <T>(input: string, init?: RequestInit) => Promise<T>;

type SpeechRecognitionResultEvent = {
  results: ArrayLike<ArrayLike<{ transcript: string }>>;
};

type SpeechRecognitionLike = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: SpeechRecognitionResultEvent) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
  start: () => void;
};

function getSpeechRecognitionCtor(): (new () => SpeechRecognitionLike) | null {
  const speechWindow = window as Window & {
    SpeechRecognition?: new () => SpeechRecognitionLike;
    webkitSpeechRecognition?: new () => SpeechRecognitionLike;
  };
  return (
    speechWindow.SpeechRecognition ??
    speechWindow.webkitSpeechRecognition ??
    null
  );
}

type SetListening = (listening: boolean) => void;

function startBrowserRecognition(appendComposerText: (text: string) => void, setSttListening: SetListening) {
  const SpeechRecognitionCtor = getSpeechRecognitionCtor();
  if (!SpeechRecognitionCtor) {
    return;
  }
  const recognition = new SpeechRecognitionCtor();
  recognition.lang = navigator.language || "en-US";
  recognition.continuous = false;
  recognition.interimResults = false;
  recognition.onresult = (event) => {
    const transcript = String(event.results[0]?.[0]?.transcript || "").trim();
    if (transcript) {
      appendComposerText(transcript);
    }
    setSttListening(false);
  };
  recognition.onerror = () => {
    setSttListening(false);
  };
  recognition.onend = () => {
    setSttListening(false);
  };
  setSttListening(true);
  recognition.start();
}

// Sends the recording to the server's Whisper endpoint and appends the transcript.
async function transcribe(chunks: Blob[], appendComposerText: (text: string) => void) {
  const blob = new Blob(chunks, { type: "audio/webm" });
  const form = new FormData();
  form.append("audio", blob, "recording.webm");
  try {
    const token = localStorage.getItem("token") || "";
    const response = await fetch("/api/v1/stt/transcribe", {
      method: "POST",
      body: form,
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    const payload = (await response.json()) as { text?: string };
    const transcript = String(payload.text || "").trim();
    if (transcript) {
      appendComposerText(transcript);
    }
  } catch (error) {
    console.error("Whisper transcription failed", error);
  }
}

// Records up to a minute from the microphone; the recording is transcribed on the server when it stops.
async function startServerRecording(
  recorderRef: MutableRefObject<MediaRecorder | null>,
  appendComposerText: (text: string) => void,
  setSttListening: SetListening,
) {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const recorder = new MediaRecorder(stream);
  const chunks: Blob[] = [];
  recorder.ondataavailable = (event) => {
    if (event.data.size > 0) {
      chunks.push(event.data);
    }
  };
  recorder.onstop = async () => {
    stream.getTracks().forEach((track) => track.stop());
    recorderRef.current = null;
    setSttListening(false);
    await transcribe(chunks, appendComposerText);
  };
  recorder.start();
  recorderRef.current = recorder;
  setSttListening(true);
  window.setTimeout(() => {
    if (recorder.state === "recording") {
      recorder.stop();
    }
  }, 60000);
}

// Asks once whether the server transcribes; a failed check counts as no.
async function askServerStt(readJson: ReadJsonFn, setSttServerAvailable: (available: boolean) => void) {
  try {
    const status = await readJson<{ available: boolean }>(
      "/api/v1/stt/status",
    );
    setSttServerAvailable(status.available);
    return status.available;
  } catch {
    setSttServerAvailable(false);
    return false;
  }
}

export function useSttInput({
  readJson,
  appendComposerText,
}: {
  readJson: ReadJsonFn;
  appendComposerText: (text: string) => void;
}) {
  const [sttListening, setSttListening] = useState(false);
  const [sttServerAvailable, setSttServerAvailable] = useState<boolean | null>(
    null,
  );
  const recorderRef = useRef<MediaRecorder | null>(null);

  const sttAvailable =
    "SpeechRecognition" in window ||
    "webkitSpeechRecognition" in window ||
    "mediaDevices" in navigator;

  const startBrowserStt = () => startBrowserRecognition(appendComposerText, setSttListening);

  const startSTT = async () => {
    if (sttListening && recorderRef.current) {
      recorderRef.current.stop();
      return;
    }

    // Known from an earlier check, else asked now (only then does the start wait for the server).
    const useServer = sttServerAvailable ?? (await askServerStt(readJson, setSttServerAvailable));

    if (!useServer) {
      startBrowserStt();
      return;
    }

    try {
      await startServerRecording(recorderRef, appendComposerText, setSttListening);
    } catch (error) {
      console.error("MediaRecorder failed, falling back to browser STT", error);
      setSttServerAvailable(false);
      startBrowserStt();
    }
  };

  useEffect(() => {
    return () => {
      if (recorderRef.current && recorderRef.current.state === "recording") {
        recorderRef.current.stop();
      }
      recorderRef.current = null;
    };
  }, []);

  return {
    sttAvailable,
    sttListening,
    startSTT,
  };
}
