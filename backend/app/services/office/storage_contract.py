"""How an uploaded Office template maps to its source, import package, and active (AI-ready) template."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .ai_template import build_ai_ready_presentation_template
from .template import office_template_doc_type_for_path, suggest_office_template_entry
from .template_package import extract_office_template_package

OFFICE_TEMPLATE_AI_ARTIFACT_DIRNAME = "ai-template"


@dataclass(frozen=True)
class OfficeTemplateStorageContract:
    """Describe how an uploaded template maps to source, cache, and active artifacts."""

    doc_type: str
    source_path: Path
    active_template_path: Path
    storage_kind: str
    package_root: Path | None = None
    package_manifest_path: Path | None = None
    generated_artifact_root: Path | None = None
    ai_template_path: Path | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "doc_type": self.doc_type,
            "storage_kind": self.storage_kind,
            "source_path": str(self.source_path),
            "active_template_path": str(self.active_template_path),
            "package_root": str(self.package_root) if self.package_root is not None else "",
            "package_manifest_path": (
                str(self.package_manifest_path) if self.package_manifest_path is not None else ""
            ),
            "generated_artifact_root": (
                str(self.generated_artifact_root) if self.generated_artifact_root is not None else ""
            ),
            "ai_template_path": str(self.ai_template_path) if self.ai_template_path is not None else "",
            "has_import_package": self.package_root is not None,
            "has_generated_ai_artifact": self.ai_template_path is not None,
        }

    def to_template_entry(
        self,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        entry = suggest_office_template_entry(self.active_template_path)
        if name is not None:
            entry["name"] = name
        if description is not None:
            entry["description"] = description
        entry["source_path"] = str(self.source_path)
        if self.package_manifest_path is not None:
            entry["package_manifest_path"] = str(self.package_manifest_path)
        if self.ai_template_path is not None:
            entry["ai_template_path"] = str(self.ai_template_path)
        entry["storage_contract"] = self.as_dict()
        return entry


def _build_presentation_storage_contract(
    *,
    source_template: Path,
    import_root: Path,
) -> OfficeTemplateStorageContract:
    manifest = extract_office_template_package(source_template, import_root)
    package_root = Path(str(manifest["package_root"])).expanduser().resolve()
    output_root = package_root / OFFICE_TEMPLATE_AI_ARTIFACT_DIRNAME
    ai_template = build_ai_ready_presentation_template(
        source_template=source_template,
        extracted_package_root=package_root,
        output_root=output_root,
    )
    ai_template_path = Path(str(ai_template.get("ai_potx") or "")).expanduser().resolve()
    if not ai_template_path.exists():
        raise ValueError("failed to build AI-ready PPTX template")
    return OfficeTemplateStorageContract(
        doc_type="pptx",
        source_path=source_template,
        active_template_path=ai_template_path,
        storage_kind="uploaded_source_with_generated_ai_template",
        package_root=package_root,
        package_manifest_path=package_root / "manifest.json",
        generated_artifact_root=output_root,
        ai_template_path=ai_template_path,
    )


def build_uploaded_office_template_entry(
    *,
    source_template: str | Path,
    import_root: str | Path,
) -> dict[str, Any]:
    source = Path(source_template).expanduser().resolve()
    doc_type = office_template_doc_type_for_path(source)
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(str(source))
    if doc_type == "pptx":
        contract = _build_presentation_storage_contract(
            source_template=source,
            import_root=Path(import_root).expanduser().resolve(),
        )
        return contract.to_template_entry(
            name=f"{source.stem} AI Template",
            description=f"AI-ready PPTX template generated from uploaded source '{source.name}'.",
        )
    contract = OfficeTemplateStorageContract(
        doc_type=doc_type,
        source_path=source,
        active_template_path=source,
        storage_kind="uploaded_source_only",
    )
    return contract.to_template_entry()


__all__ = [
    "OFFICE_TEMPLATE_AI_ARTIFACT_DIRNAME",
    "OfficeTemplateStorageContract",
    "build_uploaded_office_template_entry",
]
