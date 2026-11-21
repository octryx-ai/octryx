"""Domain model package."""


def _export_module(module):
    names = getattr(module, "__all__", [name for name in dir(module) if not name.startswith("_")])
    for name in names:
        if name in __all__ or name.startswith("_"):
            continue
        __all__.append(name)
        globals()[name] = getattr(module, name)


__all__ = []

from . import notification_delivery as _impl_notification_delivery

_export_module(_impl_notification_delivery)
