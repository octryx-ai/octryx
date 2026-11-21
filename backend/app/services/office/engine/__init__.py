"""The Office engine: Word, PowerPoint and Excel documents in-process on python-docx, python-pptx and openpyxl.

Self-contained on purpose (no ``app.*`` import): the Office tools call it in-process, and the generated build
scripts import the same modules when they run with the backend interpreter. ``api`` is the operation surface.
"""

from pathlib import Path

#: The directory a generated build script puts on ``sys.path`` to import the engine (the backend root).
IMPORT_ROOT = Path(__file__).resolve().parents[4]
