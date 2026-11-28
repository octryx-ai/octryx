"""The model set that Alembic owns."""

from __future__ import annotations

from sqlalchemy import MetaData

from .core import Base


def load_migration_metadata() -> MetaData:
    from .. import models as _models  # noqa: F401
    from ..mash.master import models as _mash_master_models  # noqa: F401

    return Base.metadata
