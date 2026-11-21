"""A Bash result Claude Code cut to a preview reaches the platform with its closing lines."""

from __future__ import annotations

from octryx_claude.hook_evidence import with_full_output_tail


def test_a_persisted_output_gets_its_end_appended(tmp_path):
    saved = tmp_path / "projects" / "x" / "s1" / "tool-results" / "bf24f5q2x.txt"
    saved.parent.mkdir(parents=True)
    saved.write_text("00:00 +0: loading /w/app/test/a_test.dart\n" + "line\n" * 5000
                     + "00:49 +395: All tests passed!\n")
    preview = (f"<persisted-output>\nOutput too large (69.7KB). Full output saved to: {saved}\n\nPreview (first 2KB):\n"
               "00:00 +0: loading /w/app/test/a_test.dart\n...\n</persisted-output>")
    hook = {"tool_name": "Bash", "tool_response": {"stdout": preview, "stderr": ""}}
    enriched = with_full_output_tail(hook)
    assert enriched["tool_response"]["stdout"].endswith("00:49 +395: All tests passed!\n")
    assert enriched["tool_response"]["stdout"].startswith("<persisted-output>")


def test_other_results_and_other_files_stay_as_they_are(tmp_path):
    plain = {"tool_name": "Bash", "tool_response": {"stdout": "ok"}}
    assert with_full_output_tail(plain) == plain
    elsewhere = {"tool_name": "Bash", "tool_response": {"stdout": f"Full output saved to: {tmp_path}/secret.txt"}}
    assert with_full_output_tail(elsewhere) == elsewhere  # only Claude Code's own tool-results files
    assert with_full_output_tail({"tool_name": "Read", "tool_response": "x"}) == {"tool_name": "Read",
                                                                                "tool_response": "x"}
