"""Deterministic text windows with explicit measurement units."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from typing import Any

from langparse.core.chunker import BaseChunker
from langparse.types import Chunk, Document


def _validate_budget(size: int, overlap: int) -> None:
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise ValueError("max_chunk_size must be a positive integer")
    if not isinstance(overlap, int) or isinstance(overlap, bool) or not 0 <= overlap < size:
        raise ValueError("overlap must be an integer between 0 and max_chunk_size - 1")


class FixedTokenChunker(BaseChunker):
    """Split encoded tokens. Default lexical units are NOT model tokens.

    The default codec preserves whitespace and groups Unicode words, whitespace,
    and individual punctuation. Supply both encoder and decoder to use a model's
    tokenizer; the caller owns that codec's lossless decoding contract.
    """

    def __init__(
        self,
        max_chunk_size: int = 1000,
        overlap: int = 0,
        *,
        encoder: Callable[[str], Sequence[Any]] | None = None,
        decoder: Callable[[Sequence[Any]], str] | None = None,
    ):
        _validate_budget(max_chunk_size, overlap)
        if (encoder is None) != (decoder is None):
            raise ValueError("encoder and decoder must be supplied together")
        self.max_chunk_size = max_chunk_size
        self.overlap = overlap
        self.encoder = encoder or (lambda text: re.findall(r"\s+|\w+|[^\w\s]", text))
        self.decoder = decoder or "".join
        self.tokenizer = "custom" if encoder is not None else "lexical"

    def chunk(self, document: Document, **kwargs) -> list[Chunk]:
        tokens = list(self.encoder(document.content))
        chunks = []
        for start in range(0, len(tokens), self.max_chunk_size - self.overlap):
            end = min(start + self.max_chunk_size, len(tokens))
            chunks.append(
                Chunk(
                    content=self.decoder(tokens[start:end]),
                    metadata={
                        **document.metadata,
                        "chunk_strategy": "fixed-token",
                        "chunk_index": len(chunks),
                        "tokenizer": self.tokenizer,
                        "token_start": start,
                        "token_end": end,
                        "token_count": end - start,
                    },
                )
            )
            if end == len(tokens):
                break
        return chunks


class SlidingWindowChunker(BaseChunker):
    """Character windows over the complete text, including block separators."""

    def __init__(self, max_chunk_size: int = 1000, overlap: int = 0):
        _validate_budget(max_chunk_size, overlap)
        self.max_chunk_size = max_chunk_size
        self.overlap = overlap

    def chunk(self, document: Document, **kwargs) -> list[Chunk]:
        chunks = []
        for start in range(0, len(document.content), self.max_chunk_size - self.overlap):
            end = min(start + self.max_chunk_size, len(document.content))
            chunks.append(
                Chunk(
                    content=document.content[start:end],
                    metadata={
                        **document.metadata,
                        "chunk_strategy": "sliding-window",
                        "chunk_index": len(chunks),
                        "size_unit": "character",
                        "char_start": start,
                        "char_end": end,
                    },
                )
            )
            if end == len(document.content):
                break
        return chunks
