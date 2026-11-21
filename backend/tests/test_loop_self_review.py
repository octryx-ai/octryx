from app.agent.loops.control._loop_self_review import _agent_requires_terminal_self_review


def test_agent_requires_terminal_self_review_for_repo_change_steps():
    assert _agent_requires_terminal_self_review(
        [{"name": "Edit Files", "allowedTools": ["write_workspace_file"]}],
        capability_type="change",
        agent_definition=None,
    )


def test_agent_skips_terminal_self_review_for_document_artifact_workflow_steps():
    assert not _agent_requires_terminal_self_review(
        [
            {
                "name": "Build Document",
                "allowedTools": [
                    "write_workspace_file",
                    "read_workspace_file",
                    "build_word_template_script",
                    "validate_office_document",
                    "get_office_document_info",
                ],
            }
        ],
        capability_type="change",
        agent_definition=None,
    )
