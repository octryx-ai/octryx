from app.web._helpers._chat_thread_groups import build_chat_thread_groups


def test_build_chat_thread_groups_nests_rows_and_preserves_numbering():
    active_session_rows = [
        {
            "id": "parent",
            "title": "Parent",
            "project_name": "Acme Orders",
            "started_at": None,
            "status": "stopped",
            "stop_reason": "user_cancelled",
            "parent_session_id": "",
            "sub_threads": [],
            "sub_thread_count": 0,
        },
        {
            "id": "child",
            "title": "Child",
            "project_name": "Acme Orders",
            "started_at": None,
            "status": "active",
            "stop_reason": "",
            "parent_session_id": "parent",
            "sub_threads": [],
            "sub_thread_count": 0,
        },
        {
            "id": "sibling",
            "title": "Sibling",
            "project_name": "Other",
            "started_at": None,
            "status": "active",
            "stop_reason": "",
            "parent_session_id": "",
            "sub_threads": [],
            "sub_thread_count": 0,
        },
    ]
    archived_session_rows = [
        {
            "id": "archived",
            "title": "Archived",
            "project_name": "Archive",
            "started_at": None,
            "status": "archived",
            "stop_reason": "",
            "parent_session_id": "",
            "sub_threads": [],
            "sub_thread_count": 0,
        }
    ]

    result = build_chat_thread_groups(
        active_session_rows=active_session_rows,
        archived_session_rows=archived_session_rows,
    )

    assert len(result.top_level_active_rows) == 2
    acme_orders_group = next(group for group in result.active_chat_groups if group["project_name"] == "Acme Orders")
    parent_row = acme_orders_group["sessions"][0]
    assert parent_row["id"] == "parent"
    assert parent_row["sub_thread_count"] == 1
    assert parent_row["sub_threads"][0]["id"] == "child"
    assert parent_row["sub_threads"][0]["status"] == "stopped"
    assert parent_row["sub_threads"][0]["stop_reason"] == "user_cancelled"
    assert parent_row["thread_number"] == 1

    other_group = next(group for group in result.active_chat_groups if group["project_name"] == "Other")
    assert other_group["sessions"][0]["thread_number"] == 2
    assert archived_session_rows[0]["thread_number"] == 3
