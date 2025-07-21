"""Invoke tasks file for cleanup, build, etc."""

from invoke import Context, task


@task
def clean(c: Context) -> None:
    """Cleans up after a test"""
    c.run("rm -rf my-state.yjs")
    c.run("rm -rf transactions")
