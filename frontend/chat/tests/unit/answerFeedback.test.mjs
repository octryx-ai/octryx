// Run: node --import ./tests/unit/register-ts.mjs --test "tests/unit/*.test.mjs"
//
// Answer feedback: the chat form sends only closed values the backend accepts (good/bad, the six
// aspects, liked/disliked), bounded texts, and nothing for an unset field; the admin filters only
// put set values on the query string.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  FEEDBACK_ASPECTS,
  MAX_FEEDBACK_TEXT_CHARS,
  buildFeedbackPayload,
  draftFromFeedback,
  toggleAspect,
} from "../../src/chat/messageFeedbackModel.ts";
import { FEEDBACK_ASPECTS as ADMIN_ASPECTS, feedbackQuery } from "../../src/admin/components/workspaceKnowledge/feedbackApi.ts";

const MODEL_SOURCE = readFileSync(
  new URL("../../../../backend/app/models/project/knowledge_answer_feedback.py", import.meta.url),
  "utf8",
).replace(/\r\n/g, "\n");

function backendEnum(name) {
  const start = MODEL_SOURCE.indexOf(`class ${name}(StrEnum):`);
  const body = MODEL_SOURCE.slice(start, MODEL_SOURCE.indexOf("\n\n\n", start));
  return [...body.matchAll(/^\s{4}[A-Z_]+ = "([a-z_]+)"$/gm)].map((match) => match[1]);
}

test("the closed values and the text bound mirror the backend contract", () => {
  assert.deepEqual([...FEEDBACK_ASPECTS], backendEnum("FeedbackAspect"));
  assert.deepEqual([...ADMIN_ASPECTS], backendEnum("FeedbackAspect"));
  assert.deepEqual(backendEnum("FeedbackRating"), ["good", "bad"]);
  assert.deepEqual(backendEnum("AspectVerdict"), ["liked", "disliked"]);
  assert.match(MODEL_SOURCE, new RegExp(`MAX_FEEDBACK_TEXT_CHARS = ${MAX_FEEDBACK_TEXT_CHARS}\\n`));
});

test("an aspect chip cycles liked, disliked, unmarked", () => {
  const liked = toggleAspect({}, "sources");
  assert.deepEqual(liked, { sources: "liked" });
  const disliked = toggleAspect(liked, "sources");
  assert.deepEqual(disliked, { sources: "disliked" });
  assert.deepEqual(toggleAspect(disliked, "sources"), {});
});

test("the payload needs a rating, trims texts, sends null for empty ones and orders aspects", () => {
  assert.equal(buildFeedbackPayload({ rating: null, liked: "x", disliked: "", aspects: {} }), null);
  assert.deepEqual(
    buildFeedbackPayload({ rating: "bad", liked: "  ", disliked: " Missing steps ", aspects: { speed: "liked", sources: "disliked" } }),
    { rating: "bad", liked: null, disliked: "Missing steps", aspects: { sources: "disliked", speed: "liked" } },
  );
  const tooLong = "x".repeat(MAX_FEEDBACK_TEXT_CHARS + 1);
  assert.equal(buildFeedbackPayload({ rating: "good", liked: tooLong, disliked: "", aspects: {} }), null);
});

test("a stored feedback becomes an editable draft; unknown values are dropped", () => {
  const draft = draftFromFeedback({
    rating: "good",
    liked: "Clear",
    disliked: null,
    aspects: { clarity: "liked", tone: "liked", sources: "maybe" },
  });
  assert.deepEqual(draft, { rating: "good", liked: "Clear", disliked: "", aspects: { clarity: "liked" } });
  assert.deepEqual(draftFromFeedback(null), { rating: null, liked: "", disliked: "", aspects: {} });
});

test("admin filters put only set values on the query string", () => {
  assert.equal(feedbackQuery({ rating: "", aspect: "", workflowKey: " " }), "");
  assert.equal(
    feedbackQuery({ rating: "bad", aspect: "tool_use", workflowKey: "knowledge-request" }),
    "?rating=bad&aspect=tool_use&workflow_key=knowledge-request",
  );
});
