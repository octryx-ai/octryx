"""Every Office artifact catalog action only reads and analyses its file."""

from app.services.office.action_catalog import office_action_entries, office_action_text


def test_every_catalog_action_only_reads():
    for file_type, path in (("docx", "a.docx"), ("pptx", "a.pptx"), ("xlsx", "a.xlsx")):
        for entry in office_action_entries(file_type):
            text = " ".join(office_action_text(path, entry["id"], mode) for mode in ("prompt", "tool_plan")).lower()
            assert not any(verb in text for verb in ("edit the", "modify", "write to", "update the file")), entry["id"]
