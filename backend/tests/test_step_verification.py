from app.scheduler.execution._step_verification import build_verification_prompt, classify_verification_response


def test_build_verification_prompt_keeps_first_attempt_plain():
    base_prompt = "Check the diff."

    assert build_verification_prompt(base_prompt, 0, 2) == base_prompt


def test_build_verification_prompt_prefixes_retry_attempts():
    prompt = build_verification_prompt("Check the diff.", 2, 3)

    assert prompt.startswith("[Fix attempt 2/3]")
    assert prompt.endswith("Check the diff.")


def test_classify_verification_response_detects_pass_and_fail_markers():
    passed, failed = classify_verification_response({"response": "✅ All checks passed"})

    assert passed is True
    assert failed is False

    passed, failed = classify_verification_response({"response": "❌ verification failed"})

    assert passed is False
    assert failed is True


def test_classify_verification_response_treats_ambiguous_text_as_neither():
    passed, failed = classify_verification_response({"response": "Looks fine to me"})

    assert passed is False
    assert failed is False
