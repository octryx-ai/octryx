from datetime import date

from app.tools.jira_impl._jira_relative_dates import infer_relative_release_date_from_message


def test_infer_relative_release_date_supports_offsets():
    today = date(2026, 4, 20)

    assert (
        infer_relative_release_date_from_message(
            "create a release in 2 weeks",
            today=today,
        )
        == "2026-05-04"
    )
    assert (
        infer_relative_release_date_from_message(
            "release in 3 days",
            today=today,
        )
        == "2026-04-23"
    )


def test_infer_relative_release_date_supports_named_shortcuts():
    today = date(2026, 4, 20)

    assert infer_relative_release_date_from_message("ship tomorrow", today=today) == "2026-04-21"
    assert infer_relative_release_date_from_message("ship next week", today=today) == "2026-04-27"


def test_infer_relative_release_date_returns_empty_for_non_matches():
    assert infer_relative_release_date_from_message("", today=date(2026, 4, 20)) == ""
    assert (
        infer_relative_release_date_from_message(
            "ship on the planned target date",
            today=date(2026, 4, 20),
        )
        == ""
    )
