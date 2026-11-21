"""README rendering for generated repository documentation: root, top-level group and module READMEs."""

# ruff: noqa: E501

from __future__ import annotations

from typing import Any

# Fixed sentences and headings of the generated READMEs. Structural markdown (tables, links, code
# fences) stays in the render functions.
_README_TEXT: dict[str, Any] = {
    "module_usage_hints": {
        "javaagent": (
            "`{module_name}` is built as a Java agent and attached to a target runtime with "
            "`-javaagent:/path/{module_name}.jar` or through the existing server/container start configuration."
        ),
        "extension": "`{module_name}` is built as an extension module and taken over into the target system's deployment pipeline.",
        "application-center": (
            "`{module_name}` is part of the application-center area and is used as a library or web component within "
            "the parent build/deployment."
        ),
        "tooling": "`{module_name}` is a helper or test tool that runs locally or in a dedicated tooling environment.",
        "default": "`{module_name}` is produced by the repository build and included in its intended target process.",
    },
    "root_overview": "`{repo_name}` contains several modules for agents, plugins, application-center components and tooling.",
    "root_sources_note": "This documentation was derived from the repository layout, the build files, selected source entry points and the existing configuration files.",
    "root_deliverables_heading": "## What this repository delivers",
    "root_deliverables": (
        "- Java agents and plugins that are attached to parent target systems.",
        "- Application-center and tooling building blocks for build, test and operations.",
        "- One README per module, so each subfolder states how its part is built and used.",
    ),
    "root_build_notes": (
        "Most modules in this repository are Maven-based Java projects.",
        "A full build typically runs from the repository root with `mvn clean install`. For targeted changes a selective module build is often the better choice.",
    ),
    "root_workflow_heading": "## Development workflow",
    "root_workflow_steps": (
        "1. Identify the affected module and its README.",
        "2. Check the module's relevant build and configuration files.",
        "3. Develop the change locally in the module and run `mvn clean test` there first.",
        "4. If the module produces runtime artifacts for agent or plugin deployment, validate the affected target integration separately.",
    ),
    "top_level_overview": "This folder contains the `{group_name}` modules of the repository.",
    "top_level_readme_note": "Use the module READMEs to see the build, entry points and expected use of each subfolder.",
    "top_level_build_notes": (
        "Prefer Maven directly in the target module or a selective build from the repository root.",
        "If a module is used in agent/plugin deployments, also check its integration configuration after the build.",
    ),
    "module_path_label": "Path: `{path}`",
    "module_purpose_heading": "## What this module is for",
    "module_usage_notes": (
        "Use this module when you need to change, build or deploy exactly this building block in the parent target system or agent setup.",
        "Do not infer changes from the module name alone; check the source, configuration and test files listed below.",
    ),
    "module_build_notes": (
        "Run the Maven build in the module directory or selectively through the root build.",
        "Typical commands:",
    ),
    "module_change_heading": "## Making changes",
    "module_change_steps": (
        "1. Review the relevant entry points and configuration files.",
        "2. Develop the change in the module.",
        "3. Run the module tests or at least validate the package build.",
        "4. If the module delivers an agent/plugin artifact, update the target integration and documentation as well.",
    ),
    "module_structure_heading": "## Directory structure",
    "module_entry_points_heading": "## Important entry points",
    "module_configuration_heading": "## Configuration and resources",
    "module_notes_main_sources": "- Main sources present: {value}",
    "module_notes_tests": "- Tests present: {value}",
    "module_notes_footer": (
        "- Update further configuration or deployment details together with the module code when behaviour changes.",
        "- If this README is not enough for operational use, module details are usually still missing in the code or the team wiki and belong there.",
    ),
}


def _module_usage_hint(module_kind: str, module_name: str) -> str:
    hints = _README_TEXT["module_usage_hints"]
    template = hints.get(module_kind) or hints["default"]
    return template.format(module_name=module_name)


def _render_root_readme(
    repo_name: str,
    modules: list[dict[str, Any]],
    top_level_names: list[str],
) -> str:
    templates = _README_TEXT
    grouped: dict[str, list[dict[str, Any]]] = {}
    for module in modules:
        grouped.setdefault(module["kind"], []).append(module)

    lines = [
        f"# {repo_name}",
        "",
        "## Overview",
        templates["root_overview"].format(repo_name=repo_name),
        templates["root_sources_note"],
        "",
        templates["root_deliverables_heading"],
        *templates["root_deliverables"],
        "",
        "## Repository Layout",
    ]
    for name in top_level_names:
        lines.append(f"- `{name}/`")
    lines.extend(
        [
            "",
            "## Build",
            *templates["root_build_notes"],
            "",
            templates["root_workflow_heading"],
            *templates["root_workflow_steps"],
            "",
            "## Module Overview",
        ]
    )
    for kind, kind_modules in grouped.items():
        lines.append(f"### {kind}")
        lines.append("")
        lines.append("| Module | Artifact | Packaging | README |")
        lines.append("| --- | --- | --- | --- |")
        for module in kind_modules:
            lines.append(
                f"| `{module['path']}` | `{module['artifact_id']}` | `{module['packaging'] or '-'}` | "
                f"[README]({module['path']}/README.md) |"
            )
        lines.append("")
    lines.extend(
        [
            "## Top-Level Documentation",
            "- [application-center/README.md](application-center/README.md)",
            "- [javaagent/README.md](javaagent/README.md)",
            "- [extensions/README.md](extensions/README.md)",
            "- [tooling/README.md](tooling/README.md)",
        ]
    )
    return "\n".join(lines) + "\n"


def _render_top_level_readme(group_name: str, modules: list[dict[str, Any]]) -> str:
    templates = _README_TEXT
    lines = [
        f"# {group_name}",
        "",
        "## Overview",
        templates["top_level_overview"].format(group_name=group_name),
        templates["top_level_readme_note"],
        "",
        "## Contained Modules",
        "| Module | Artifact | Packaging | Tests |",
        "| --- | --- | --- | --- |",
    ]
    for module in modules:
        lines.append(
            f"| `{module['name']}` | `{module['artifact_id']}` | `{module['packaging'] or '-'}` | "
            f"{'yes' if module['has_tests'] else 'no'} |"
        )
    lines.extend(
        [
            "",
            "## Build and Validation",
            *templates["top_level_build_notes"],
            "",
            "## Module READMEs",
        ]
    )
    for module in modules:
        lines.append(f"- [{module['name']}/README.md]({module['name']}/README.md)")
    return "\n".join(lines) + "\n"


def _module_overview_lines(module: dict[str, Any]) -> list[str]:
    templates = _README_TEXT
    lines = [
        f"# {module['name']}",
        "",
        "## Overview",
        templates["module_path_label"].format(path=module["path"]),
        f"Artifact: `{module['artifact_id']}`",
    ]
    if module.get("group_id"):
        lines.append(f"Group ID: `{module['group_id']}`")
    if module.get("packaging"):
        lines.append(f"Packaging: `{module['packaging']}`")
    lines.extend(
        [
            "",
            templates["module_purpose_heading"],
            _module_usage_hint(module["kind"], module["name"]),
            "",
            "## Usage",
            *templates["module_usage_notes"],
            "",
            "## Build",
            *templates["module_build_notes"],
            "```bash",
            "mvn clean test",
            "mvn package",
            "```",
            "",
            templates["module_change_heading"],
            *templates["module_change_steps"],
        ]
    )
    return lines


def _module_listing_lines(module: dict[str, Any]) -> list[str]:
    templates = _README_TEXT
    lines: list[str] = []
    if module["top_level_entries"]:
        lines.extend(["", templates["module_structure_heading"]])
        for entry in module["top_level_entries"]:
            lines.append(f"- `{entry}`")
    if module["key_files"]:
        lines.extend(["", "## Key Files"])
        for file_path in module["key_files"]:
            lines.append(f"- `{file_path}`")
    if module["notable_sources"]:
        lines.extend(["", templates["module_entry_points_heading"]])
        for source in module["notable_sources"]:
            package_prefix = f"`{source['package']}` · " if source.get("package") else ""
            lines.append(f"- {package_prefix}`{source['path']}`")
    if module["config_files"]:
        lines.extend(["", templates["module_configuration_heading"]])
        for file_path in module["config_files"]:
            lines.append(f"- `{file_path}`")
    if module["test_files"]:
        lines.extend(["", "## Tests"])
        for file_path in module["test_files"]:
            lines.append(f"- `{file_path}`")
    return lines


def _render_module_readme(module: dict[str, Any]) -> str:
    templates = _README_TEXT
    lines = [*_module_overview_lines(module), *_module_listing_lines(module)]
    lines.extend(
        [
            "",
            "## Notes",
            templates["module_notes_main_sources"].format(value="yes" if module["has_main_sources"] else "no"),
            templates["module_notes_tests"].format(value="yes" if module["has_tests"] else "no"),
            *templates["module_notes_footer"],
        ]
    )
    return "\n".join(lines) + "\n"
