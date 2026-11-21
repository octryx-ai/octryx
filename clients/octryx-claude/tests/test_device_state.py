

def test_a_folder_that_is_not_a_git_checkout_gets_a_clone_note(tmp_path):
    """Fresh-install test: the first run paused on an empty device folder; enable now says what to do."""
    from octryx_claude import device_state

    empty = tmp_path / "demo-shop"
    empty.mkdir()
    assert device_state.checkout_note(str(empty)).startswith(f"note: {empty} is not a git checkout")
    (empty / ".git").mkdir()
    assert device_state.checkout_note(str(empty)) == ""
