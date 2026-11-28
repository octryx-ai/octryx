from pathlib import Path

from app.tools.office_impl._office_core_helpers import _resolve_builtin_generic_presentation_template
from app.tools.office_impl._office_presentation_normalization import _normalize_slide_spec
from app.tools.office_impl._office_presentation_script import BuildPresentationScriptTool


def test_normalize_slide_spec_maps_compose_role_to_supported_layout():
    slide = _normalize_slide_spec(
        {
            "role": "title_cover",
            "title": "Enterprise LLM Strategy",
            "subtitle": "Benefits, risks and governance",
        }
    )

    assert slide["layout_type"] == "title"
    assert slide["title"] == "Enterprise LLM Strategy"
    assert "Benefits" in slide["subtitle"]


def test_build_presentation_script_uses_updated_bullets_and_label_sizing():
    tool = BuildPresentationScriptTool()

    code = tool._build_text_ops_code(
        [
            {
                "layout_type": "bullets",
                "title": "Implementation Strategy",
                "subtitle": "Phased rollout",
                "bullets": ["Pilot", "Scale", "Operate"],
            },
            {
                "layout_type": "four_columns",
                "title": "Key Areas",
                "columns": [
                    {"label": "Speed", "body": "Faster delivery"},
                    {"label": "Quality", "body": "Better outputs"},
                    {"label": "Risk", "body": "Safer rollout"},
                    {"label": "Governance", "body": "Clear controls"},
                ],
            },
        ]
    )

    assert tool._SOURCE_INDEX["bullets"] == 3
    assert 'set_text(ops, "/slide[1]/shape[4]", """Implementation Strategy"""' in code
    assert 'set_text(ops, "/slide[1]/shape[3]", """Phased rollout""", size="16pt")' in code
    assert 'set_text(ops, "/slide[1]/shape[1]", """Pilot\nScale\nOperate"""' in code
    assert 'size="16pt"' in code


def test_builtin_generic_presentation_template_fallback_is_available():
    template_path, detail = _resolve_builtin_generic_presentation_template()

    assert template_path == Path(detail["source_path"])
    assert template_path.exists()
    assert template_path.suffix.lower() == ".potx"
    assert int(detail["source_slide_count"]) == 0
    assert detail["fallback_mode"] == "builtin_neutral"
