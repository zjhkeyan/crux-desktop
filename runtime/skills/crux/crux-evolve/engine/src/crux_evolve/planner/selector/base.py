"""Base selector interface for CruxEvolve.

This module defines the abstract interface for selectors that choose
operators or objects based on various selection strategies.
"""

from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from crux_evolve.utils.registry import Registrable

T = TypeVar("T")


class BaseSelector(ABC, Generic[T], Registrable):
    """Abstract base class for selectors.

    Selectors are responsible for choosing one or more items from a pool
    based on different selection strategies (random, weighted, tournament, etc.).
    """

    def __init__(self, items: list[T] | None = None, config: dict[str, Any] | None = None):
        """Initialize the selector.

        Args:
            items: List of items to select from
            config: Configuration for the selector
        """
        self.items = items or []
        self.config = config or {}
        self.selection_strategy = self.config.get("selection_strategy", "random")

    def add_item(self, item: T) -> None:
        """Add an item to the selector pool.

        Args:
            item: Item to add
        """
        self.items.append(item)

    def remove_item(self, item: T) -> None:
        """Remove an item from the selector pool.

        Args:
            item: Item to remove
        """
        if item in self.items:
            self.items.remove(item)

    def update_weight(self, item: T, weight: float) -> None:
        """Update the weight for a specific item.

        Args:
            item: Item to update
            weight: New weight value
        """
        pass  # Override in subclasses if needed

    @abstractmethod
    def select(self, n: int = 1, **kwargs) -> T | list[T]:
        """Select one or more items from the pool.

        Args:
            n: Number of items to select
            **kwargs: Additional selection parameters

        Returns:
            Selected item(s)
        """
        ...

    def select_one(self, **kwargs) -> T:
        """Select a single item from the pool.

        Args:
            **kwargs: Additional selection parameters

        Returns:
            Selected item
        """
        result = self.select(1, **kwargs)
        return result[0] if isinstance(result, list) else result
