from app.services.teams_calling.wake_word import WakeWordPolicy, parse_wake_words


def test_parse_wake_words_defaults_when_empty():
    assert parse_wake_words("") == ["hey octryx", "octryx"]


def test_wake_word_policy_detects_and_strips_command_prefix():
    policy = WakeWordPolicy.from_config({"call_wake_words": "hey octryx,octryx"})

    decision = policy.evaluate("Hey Octryx, what is the status?")

    assert decision.should_respond is True
    assert decision.matched_wake_word == "hey octryx"
    assert decision.command_text == "what is the status?"


def test_wake_word_policy_ignores_unaddressed_text_when_required():
    policy = WakeWordPolicy.from_config({})

    decision = policy.evaluate("We should discuss the release date.")

    assert decision.should_respond is False
    assert decision.command_text == "We should discuss the release date."


def test_wake_word_policy_can_be_disabled_for_push_to_talk_style_calls():
    policy = WakeWordPolicy.from_config({"call_require_wake_word": False})

    decision = policy.evaluate("Please summarize the meeting.")

    assert decision.should_respond is True
    assert decision.command_text == "Please summarize the meeting."
