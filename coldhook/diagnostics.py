"""Stage-aware diagnostics shared by the CLI and Python API."""
from contextlib import contextmanager
from functools import wraps
import inspect
import logging
import time

log = logging.getLogger("coldhook")


class DiagnosticError(RuntimeError):
    pass


@contextmanager
def stage(name):
    start = time.monotonic()
    log.info("Начало: %s", name)
    try:
        yield
    except Exception as exc:
        raise DiagnosticError(f"{name}: {type(exc).__name__}: {exc}") from exc
    else:
        log.info("Готово: %s (%.2f с)", name, time.monotonic() - start)


def traced(name, *fields):
    def decorate(func):
        @wraps(func)
        def wrapped(*args, **kwargs):
            values = inspect.signature(func).bind(*args, **kwargs).arguments
            context = ", ".join(f"{key}={values[key]}" for key in fields if key in values)
            with stage(f"{name} [{context}]" if context else name):
                return func(*args, **kwargs)
        return wrapped
    return decorate
