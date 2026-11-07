"""Harbor ACP adapter for NeuriCo."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .agent import NeuricoHarborAgent

__all__ = ["NeuricoHarborAgent"]


def __getattr__(name: str) -> Any:
    """Keep NeuriCo imports lazy until the container Git preflight completes."""
    if name == "NeuricoHarborAgent":
        from .agent import NeuricoHarborAgent

        return NeuricoHarborAgent
    raise AttributeError(name)
