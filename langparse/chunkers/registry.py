"""Explicit registry for document-text chunkers; workbook routing stays structural."""

from collections.abc import Callable

from langparse.chunkers.semantic import SemanticChunker
from langparse.chunkers.text import FixedTokenChunker, SlidingWindowChunker, _validate_budget
from langparse.core.chunker import BaseChunker

_FACTORIES: dict[str, Callable[..., BaseChunker]] = {
    "semantic": SemanticChunker,
    "fixed-token": FixedTokenChunker,
    "sliding-window": SlidingWindowChunker,
}


def register_chunker(name: str, factory: Callable[..., BaseChunker]) -> None:
    if not isinstance(name, str) or not name.strip() or not callable(factory):
        raise ValueError("A non-empty name and callable chunker factory are required")
    if name in _FACTORIES:
        raise ValueError(f"Chunk strategy {name!r} is already registered")
    _FACTORIES[name] = factory


def available_chunkers() -> tuple[str, ...]:
    return tuple(sorted(_FACTORIES))


def create_chunker(name: str = "semantic", **options) -> BaseChunker:
    if name not in _FACTORIES:
        raise ValueError(
            f"Unknown chunk strategy {name!r}. Available: {', '.join(available_chunkers())}"
        )
    if name == "semantic":
        _validate_budget(options.get("max_chunk_size", 1000), options.get("overlap", 0))
    result = _FACTORIES[name](**options)
    if not isinstance(result, BaseChunker):
        raise TypeError("Chunker factory must return a BaseChunker")
    return result
