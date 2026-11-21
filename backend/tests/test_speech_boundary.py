from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1] / "app"

ALLOWED_INTERNAL_IMPORT_FILES = {
    Path("services/stt/__init__.py"),
    Path("services/stt/azure_speech.py"),
    Path("services/stt/aws_transcribe.py"),
    Path("services/tts/__init__.py"),
}

FORBIDDEN_IMPORTS = (
    "services.stt.service",
    "services.tts.service",
)


def test_app_code_uses_speech_package_boundary() -> None:
    violations: list[str] = []
    for path in APP_ROOT.rglob("*.py"):
        relative = path.relative_to(APP_ROOT)
        if relative in ALLOWED_INTERNAL_IMPORT_FILES:
            continue
        text = path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_IMPORTS:
            if forbidden in text:
                violations.append(f"{relative}: imports {forbidden}")

    assert violations == []
