"""Every Office artifact catalog action only reads and analyses its file."""

from app.services.office.action_catalog import office_action_catalog


def test_every_catalog_action_only_reads():
    # No catalog action edits its file.
    for file_type, path in (("docx", "a.docx"), ("pptx", "a.pptx"), ("xlsx", "a.xlsx")):
        for action in office_action_catalog(path, file_type):
            text = f"{action['prompt']} {action['tool_plan']}".lower()
            assert not any(verb in text for verb in ("edit the", "modify", "write to", "update the file")), action["id"]
