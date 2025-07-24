import pytest
import trio
from functools import wraps

pytest_plugins = ["tellus.tests.pytest_plugin"]


def trio_test(func):
    """Decorator to run async tests with Trio."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        return trio.run(func, *args, **kwargs)

    return wrapper
