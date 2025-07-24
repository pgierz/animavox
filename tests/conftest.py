import trio
from functools import wraps


def trio_test(func):
    """Decorator to run async tests with Trio."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        return trio.run(func, *args, **kwargs)

    return wrapper
