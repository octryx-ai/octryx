"""The model set that Alembic owns.

``alembic/env.py`` uses this metadata as its migration target, and the parity tests check that no runtime
entry point registers a table outside it. It is the ``app.models`` registry plus the MASH master models,
whose routers are always mounted (``app/http_setup.py``).
They are loaded here rather than in ``app.models`` so the core model registry does not grow; which MASH
tables stay in use is decided in.
"""

from __future__ import annotations

from sqlalchemy import MetaData

from .core import Base


def load_migration_metadata() -> MetaData:
    """Register every model whose table the migrations own and return their shared metadata."""
    from .. import models as _models  # noqa: F401
    from ..mash.master import models as _mash_master_models  # noqa: F401

    return Base.metadata
