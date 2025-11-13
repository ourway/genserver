"""
Type hints and aliases for the GenServer library.
"""

from typing import TypeVar

CallMsg = TypeVar("CallMsg")
"""Type variable for call messages."""

CastMsg = TypeVar("CastMsg")
"""Type variable for cast messages."""

StateType = TypeVar("StateType")
"""Type variable for TypedGenServer state."""

__all__ = ["CallMsg", "CastMsg", "StateType"]  # Ensure StateType is exported
