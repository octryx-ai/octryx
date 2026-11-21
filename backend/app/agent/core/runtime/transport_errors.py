"""Typed translation of provider transport failures (roadmap 3).

A provider client wraps each network call in :func:`translate_transport_errors`.
An ``httpx`` or ``botocore`` transport exception (connect error, connect/read
timeout, a connection closed mid-response) leaves the block as a
``ProviderRuntimeError`` whose class comes from the exception *type*
(``runtime_errors.transport_error_class``) and whose classification source is
``exception_type``. Retry, runtime fallback and the Model Policy alias failover
therefore decide on a typed fact instead of on the exception's wording.

The message is fixed: the provider label and the exception type name. The
original exception text is never copied, because it can name the endpoint URL,
a proxy, or a resolver answer, and the engine persists ``str(exc)`` into the
runtime attempt evidence. The translation is raised ``from None`` for the same
reason, so no traceback or logged exception prints the original. Anything that is
not a transport failure passes through unchanged.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from .runtime_errors import CLASSIFICATION_SOURCE_EXCEPTION_TYPE, ProviderRuntimeError, transport_error_class


def typed_transport_error(exc: BaseException, *, label: str) -> ProviderRuntimeError | None:
    """The typed provider error for a transport exception, or ``None`` when ``exc`` is not one."""
    if isinstance(exc, ProviderRuntimeError):
        return None
    error_class = transport_error_class(exc)
    if error_class is None:
        return None
    return ProviderRuntimeError(
        f"{label} transport failure ({type(exc).__name__})",
        error_class=error_class,
        error_class_source=CLASSIFICATION_SOURCE_EXCEPTION_TYPE,
    )


@contextmanager
def translate_transport_errors(label: str) -> Iterator[None]:
    """Re-raise a transport exception from the block as a typed ``ProviderRuntimeError``."""
    try:
        yield
    except Exception as exc:
        typed = typed_transport_error(exc, label=label)
        if typed is None:
            raise
        raise typed from None


__all__ = ["translate_transport_errors", "typed_transport_error"]
