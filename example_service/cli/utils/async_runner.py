"""Utilities for running async operations in CLI commands."""

import asyncio
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, TypeVar

T = TypeVar("T")


def run_async[T](coro: Awaitable[T]) -> T:
    """
    Run an async coroutine in a new event loop.

    Args:
        coro: The coroutine to run

    Returns:
        The result of the coroutine
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If there's already a running loop, create a new one
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    try:
        return loop.run_until_complete(coro)
    finally:
        # Don't close the loop if it was already running
        pass


def async_command(func: Callable[..., Awaitable[Any]]) -> Callable[..., Any]:
    """
    Decorator to convert an async function into a Click command.

    Usage:
        @click.command()
        @async_command
        async def my_command():
            await some_async_operation()
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return run_async(func(*args, **kwargs))

    return wrapper


def coro[T](f: Callable[..., Awaitable[T]]) -> Callable[..., T]:
    """
    Decorator that makes an async function synchronous for Click.

    This is useful for Click commands that need to run async code.

    Usage:
        @cli.command()
        @coro
        async def my_command():
            result = await some_async_function()
            click.echo(result)
    """

    @wraps(f)
    def wrapper(*args: Any, **kwargs: Any) -> T:
        return asyncio.run(f(*args, **kwargs))

    return wrapper
