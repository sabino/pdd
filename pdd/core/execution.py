"""Isolate server requests from remote dispatch and prompt resource expansion."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_SERVER_EXECUTION: ContextVar[bool] = ContextVar("pdd_server_execution", default=False)


def is_server_execution() -> bool:
    return _SERVER_EXECUTION.get()


@contextmanager
def server_execution() -> Iterator[None]:
    token = _SERVER_EXECUTION.set(True)
    try:
        yield
    finally:
        _SERVER_EXECUTION.reset(token)
