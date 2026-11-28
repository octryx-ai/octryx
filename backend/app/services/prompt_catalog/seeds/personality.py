"""Seeds of the communication-preference lines built from a user's personality settings."""

from __future__ import annotations

from ..contract import PromptKeySpec

AREA = "personality"

SPECS: tuple[PromptKeySpec, ...] = (
    PromptKeySpec(
        key="personality.language.de",
        area=AREA,
        title="Answer language: de",
        seed=(
            "Respond in the language of the person's latest message; when that message shows no clear language, "
            "respond in German."
        ),
        description="First line of the Communication Preferences section for this personality language.",
    ),
    PromptKeySpec(
        key="personality.language.fr",
        area=AREA,
        title="Answer language: fr",
        seed=(
            "Respond in the language of the person's latest message; when that message shows no clear language, "
            "respond in French."
        ),
        description="First line of the Communication Preferences section for this personality language.",
    ),
    PromptKeySpec(
        key="personality.detail.en.minimal",
        area=AREA,
        title="Detail level minimal (en)",
        seed="Give extremely short answers. Only the essentials.",
        description="Detail-level line; English lines serve every personality language.",
    ),
    PromptKeySpec(
        key="personality.detail.en.standard",
        area=AREA,
        title="Detail level standard (en)",
        seed="Give clear, compact answers.",
        description="Detail-level line; English lines serve every personality language.",
    ),
    PromptKeySpec(
        key="personality.detail.en.detailed",
        area=AREA,
        title="Detail level detailed (en)",
        seed="Explain context. Show relevant logs, metrics and events.",
        description="Detail-level line; English lines serve every personality language.",
    ),
    PromptKeySpec(
        key="personality.detail.en.verbose",
        area=AREA,
        title="Detail level verbose (en)",
        seed="Be thorough. Explain every step.",
        description="Detail-level line; English lines serve every personality language.",
    ),
    PromptKeySpec(
        key="personality.style.en.technical",
        area=AREA,
        title="Communication style technical (en)",
        seed="Use technical terminology. Be precise.",
        description="Communication-style line; English lines serve every personality language.",
    ),
    PromptKeySpec(
        key="personality.style.en.casual",
        area=AREA,
        title="Communication style casual (en)",
        seed="Be relaxed and friendly.",
        description="Communication-style line; English lines serve every personality language.",
    ),
    PromptKeySpec(
        key="personality.style.en.formal",
        area=AREA,
        title="Communication style formal (en)",
        seed="Be polite and professional.",
        description="Communication-style line; English lines serve every personality language.",
    ),
    PromptKeySpec(
        key="personality.style.en.concise",
        area=AREA,
        title="Communication style concise (en)",
        seed="Answer as briefly as possible. Prefer bullet points.",
        description="Communication-style line; English lines serve every personality language.",
    ),
)
