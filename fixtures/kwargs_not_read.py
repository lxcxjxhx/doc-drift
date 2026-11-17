"""Fixture: an implementation that takes *args/**kwargs above a set of overloads.

The docstring describes the overload signature, not the implementation's parameter list,
so reporting `alpha` as a stale argument would be wrong.
"""
from typing import overload


@overload
def build(self, alpha: str, beta: int) -> None: ...


@overload
def build(self, alpha: str) -> None: ...


def build(self, *args, **kwargs) -> None:
    """
    Build something.

    Args:
        alpha: documented for the overload, not for this body
        beta: same
    """
    return None
