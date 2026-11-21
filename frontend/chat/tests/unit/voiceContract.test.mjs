// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/voiceContract.test.mjs
//
// Voice & speech (S7): only providers the backend builds, every field round-
// trips, a toggle never wipes the provider settings, a masked key is never written back.

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  MASK,
  STT_PROVIDERS,
  TTS_PROVIDERS,
  readStt,
  readTts,
  sttSaveBody,
  ttsReady,
  ttsSaveBodies,
} from "../../src/admin/components/voice/voiceContract.ts";

test("only providers the backend builds are offered", () => {
  assert.deepEqual(TTS_PROVIDERS.map((item) => item.id), ["openai", "elevenlabs", "aws_polly"]);
  assert.deepEqual(STT_PROVIDERS.map((item) => item.id), ["openai_whisper", "local_whisper", "aws_transcribe", "azure_speech"]);
});

test("turning speech off keeps the provider settings and sends no masked key", () => {
  const state = readTts(
    { enabled: true, default_voice: "nova", providers: [{ provider: "openai", enabled: true, priority: 0, config: { model: "tts-1-hd" } }] },
    { openai_api_key: MASK },
  );
  assert.equal(ttsReady(state), true);
  const bodies = ttsSaveBodies({ ...state, enabled: false }, { openai_api_key: MASK });
  assert.deepEqual(bodies.keys, {});
  assert.deepEqual(bodies.provider, { provider: "openai", enabled: false, priority: 0, config: { model: "tts-1-hd" } });
  assert.deepEqual(bodies.config, { enabled: false, default_voice: "nova" });
});

test("a Polly save carries both keys and the region", () => {
  const state = { enabled: true, provider: "aws_polly", voice: "Joanna", settings: { region: "eu-west-1" }, keys: {} };
  const bodies = ttsSaveBodies(state, { aws_polly_access_key_id: "a", aws_polly_secret_key: "b" });
  assert.deepEqual(bodies.keys, { aws_polly_access_key_id: "a", aws_polly_secret_key: "b" });
  assert.equal(bodies.provider.config.region, "eu-west-1");
});

test("speech to text sends only the chosen provider's typed values", () => {
  const state = readStt({ active_provider: "aws_transcribe", language: "de-DE", providers: {
    aws_transcribe: { access_key_id: MASK, secret_access_key: MASK, region: "eu-central-1" } } });
  assert.deepEqual(sttSaveBody(state), { active_provider: "aws_transcribe", language: "de-DE",
    providers: { aws_transcribe: { region: "eu-central-1" } } });
});
