from app.tools._confluence_write import build_add_comment_payload, build_create_page_payload, build_update_page_payload


def test_build_create_page_payload_includes_optional_parent():
    payload = build_create_page_payload(
        space_key="ENG",
        title="Runbook",
        storage_content="<p>hello</p>",
        parent_id="123",
    )

    assert payload == {
        "type": "page",
        "title": "Runbook",
        "space": {"key": "ENG"},
        "body": {"storage": {"value": "<p>hello</p>", "representation": "storage"}},
        "ancestors": [{"id": "123"}],
    }


def test_build_create_page_payload_omits_parent_when_not_provided():
    payload = build_create_page_payload(
        space_key="ENG",
        title="Runbook",
        storage_content="<p>hello</p>",
    )

    assert "ancestors" not in payload


def test_build_update_page_payload_sets_next_version():
    payload = build_update_page_payload(
        title="Runbook v2",
        version_number=4,
        storage_content="<p>updated</p>",
    )

    assert payload == {
        "type": "page",
        "title": "Runbook v2",
        "version": {"number": 4},
        "body": {"storage": {"value": "<p>updated</p>", "representation": "storage"}},
    }


def test_build_add_comment_payload_wraps_page_container():
    payload = build_add_comment_payload(
        page_id="987",
        storage_content="<p>ship it</p>",
    )

    assert payload == {
        "type": "comment",
        "container": {"id": "987", "type": "page"},
        "body": {"storage": {"value": "<p>ship it</p>", "representation": "storage"}},
    }
