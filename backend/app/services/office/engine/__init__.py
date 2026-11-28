"""The Office engine: Word, PowerPoint and Excel documents in-process on python-docx, python-pptx and openpyxl."""

from pathlib import Path

#: The directory a generated build script puts on ``sys.path`` to import the engine (the backend root).
IMPORT_ROOT = Path(__file__).resolve().parents[4]
