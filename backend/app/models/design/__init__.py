"""Domain model package."""


def _export_module(module):
    names = getattr(module, "__all__", [name for name in dir(module) if not name.startswith("_")])
    for name in names:
        if name in __all__ or name.startswith("_"):
            continue
        __all__.append(name)
        globals()[name] = getattr(module, name)


__all__ = []

from . import design_artifact as _impl_design_artifact

_export_module(_impl_design_artifact)

from . import design_trace_sync_template as _impl_design_trace_sync_template

_export_module(_impl_design_trace_sync_template)

from . import design_traceability as _impl_design_traceability

_export_module(_impl_design_traceability)
