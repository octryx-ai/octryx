"""Seeds of the fixed answer texts the loop persists as the assistant message: salvage answers after a
provider failure, synthetic success and report answers, the coding and migration completion reports, the
read-only sub-agent wrap-up and the governed pull request description.

The only code copy of these texts. Protocol prefixes other code parses (``Agent error:``, ``Agent stopped
because ``, ``[Agent reached maximum tool call iterations]``) stay in code.
"""

from __future__ import annotations

from ..contract import PromptKeySpec
from .answer_reports import SPECS as REPORT_SPECS

AREA = "answer"

_SALVAGE_SPECS: tuple[PromptKeySpec, ...] = (
    PromptKeySpec(
        key="answer.provider_limit_suffix",
        area=AREA,
        title="Salvage: provider limit note",
        seed="The final narrative phrasing could not be generated because of a temporary provider limit.",
        description="Closing sentence of every salvage answer ({provider_limit_suffix}).",
    ),
    PromptKeySpec(
        key="answer.salvage.presentation",
        area=AREA,
        title="Salvage: generated presentation",
        seed=(
            "I already generated the presentation about {topic}. {artifact_line}\n"
            "\n"
            "Suggested structure:\n"
            "1. Overview\n"
            "2. Core capabilities\n"
            "3. Integration\n"
            "4. Operational considerations\n"
            "\n"
            "{provider_limit_suffix}"
        ),
        placeholders=frozenset({"artifact_line", "provider_limit_suffix", "topic"}),
    ),
    PromptKeySpec(
        key="answer.salvage.presentation_file",
        area=AREA,
        title="Salvage: presentation file line",
        seed="Created file: `{relative_path}`.",
        placeholders=frozenset({"relative_path"}),
    ),
    PromptKeySpec(
        key="answer.salvage.presentation_file_unknown",
        area=AREA,
        title="Salvage: presentation file unknown",
        seed="The file was created successfully.",
    ),
    PromptKeySpec(
        key="answer.salvage.outline",
        area=AREA,
        title="Salvage: presentation outline from evidence",
        seed=(
            "I already collected enough evidence for an initial presentation structure.\n"
            "\n"
            "Slide 1: Overview\n"
            "- target picture and purpose of the topic\n"
            "\n"
            "Slide 2: Core capabilities\n"
            "- key responsibilities and functional role\n"
            "\n"
            "Slide 3: Integration\n"
            "- integration into deployment, configuration, and runtime paths\n"
            "\n"
            "Slide 4: Operational considerations\n"
            "- dependencies, configuration, and operational notes\n"
            "\n"
            "{provider_limit_suffix}"
        ),
        placeholders=frozenset({"provider_limit_suffix"}),
    ),
    PromptKeySpec(
        key="answer.salvage.weekly_summary",
        area=AREA,
        title="Salvage: weekly summary",
        seed=(
            "I already collected the changes from Jira, Bitbucket, and Confluence.\n"
            "\n"
            "Current status:\n"
            "{jira_line}\n"
            "{bitbucket_line}\n"
            "{confluence_line}\n"
            "\n"
            "{provider_limit_suffix}"
        ),
        placeholders=frozenset({"bitbucket_line", "confluence_line", "jira_line", "provider_limit_suffix"}),
    ),
    PromptKeySpec(
        key="answer.salvage.weekly_jira",
        area=AREA,
        title="Salvage: weekly summary Jira line",
        seed="- Jira: {jira_count} relevant issues",
        placeholders=frozenset({"jira_count"}),
    ),
    PromptKeySpec(
        key="answer.salvage.weekly_bitbucket",
        area=AREA,
        title="Salvage: weekly summary Bitbucket line",
        seed="- Bitbucket: {bitbucket_count} relevant commits",
        placeholders=frozenset({"bitbucket_count"}),
    ),
    PromptKeySpec(
        key="answer.salvage.weekly_confluence",
        area=AREA,
        title="Salvage: weekly summary Confluence line",
        seed="- Confluence: {confluence_count} relevant page updates",
        placeholders=frozenset({"confluence_count"}),
    ),
    PromptKeySpec(
        key="answer.salvage.office_artifact",
        area=AREA,
        title="Salvage: generated Office artifact",
        seed=(
            "I already generated the requested Office artifact: `{relative_path}`.\n"
            "\n"
            "{provider_limit_suffix}"
        ),
        placeholders=frozenset({"provider_limit_suffix", "relative_path"}),
    ),
    PromptKeySpec(
        key="answer.tool_status.empty",
        area=AREA,
        title="Tool status: processing loaded results",
        seed="I am now processing the results that are already loaded.",
    ),
    PromptKeySpec(
        key="answer.tool_status.single",
        area=AREA,
        title="Tool status: one tool",
        seed="I am now gathering the missing evidence with `{tool_name}`.",
        placeholders=frozenset({"tool_name"}),
    ),
    PromptKeySpec(
        key="answer.tool_status.multi",
        area=AREA,
        title="Tool status: several tools",
        seed="I am now gathering the missing evidence with {tool_names}.",
        placeholders=frozenset({"tool_names"}),
        description="{tool_names} is the back-quoted preview of up to three tool names.",
    ),
    PromptKeySpec(
        key="answer.runtime.unreachable",
        area=AREA,
        title="Runtime unreachable answer",
        seed="No runtime is currently reachable. Please try again later.",
        description="Answer when every runtime attempt timed out or was unreachable.",
    ),
    PromptKeySpec(
        key="answer.content.refused",
        area=AREA,
        title="Content policy refusal answer",
        seed=("This request was not sent to a model: a platform content policy refused it "
              "(for example a prompt-injection attempt). Rephrase the request and try again."),
        description="Answer when a platform content policy refused the model request before it was sent.",
    ),
    PromptKeySpec(
        key="answer.knowledge.nothing_documented",
        area=AREA,
        title="Knowledge search found nothing",
        seed="I searched the Workspace Knowledge, but found nothing documented about this.",
        description=(
            "English answer when the governed Knowledge search returned no result (the German variant is product "
            "content)."
        ),
    ),
    PromptKeySpec(
        key="answer.diagram.complete",
        area=AREA,
        title="Diagram success: complete",
        seed="Diagram complete.",
    ),
    PromptKeySpec(
        key="answer.diagram.artifact",
        area=AREA,
        title="Diagram success: artifact line",
        seed="Artifact: `{artifact_ref}`.",
        placeholders=frozenset({"artifact_ref"}),
    ),
    PromptKeySpec(
        key="answer.diagram.title",
        area=AREA,
        title="Diagram success: title line",
        seed="Title: `{title}`.",
        placeholders=frozenset({"title"}),
    ),
    PromptKeySpec(
        key="answer.diagram.created",
        area=AREA,
        title="Diagram success: created",
        seed="The draw.io diagram was created successfully.",
    ),
)

# The report answers live in ``answer_reports`` to keep each module small.
SPECS: tuple[PromptKeySpec, ...] = _SALVAGE_SPECS + REPORT_SPECS
