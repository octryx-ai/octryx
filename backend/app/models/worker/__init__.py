"""Domain model package."""


def _export_module(module):
    names = getattr(module, "__all__", [name for name in dir(module) if not name.startswith("_")])
    for name in names:
        if name in __all__ or name.startswith("_"):
            continue
        __all__.append(name)
        globals()[name] = getattr(module, name)


__all__ = []

from . import teaming as _impl_teaming

_export_module(_impl_teaming)

from . import worker as _impl_worker

_export_module(_impl_worker)

from . import worker_pool as _impl_worker_pool

_export_module(_impl_worker_pool)
