// Workspace voice settings: TTS provider, global TTS config and stored project voice config shapes.
export type TtsProvider = {
  id: string;
  name: string;
  voices: string[];
  has_key: boolean;
  installed?: boolean;
};

export type GlobalTtsConfig = {
  enabled: boolean;
  default_voice: string;
  default_speed: number;
  providers: TtsProvider[];
};

export type ProjectConfig = {
  tts?: {
    enabled?: boolean;
    provider?: string;
    default_voice?: string;
    default_speed?: number;
  };
  stt?: {
    enabled?: boolean;
    provider?: string;
  };
};
