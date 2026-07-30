from abc import ABC, abstractmethod

from langparse.types import Chunk, Document


class BaseChunker(ABC):
    """
    Abstract base class for all text chunkers.
    """

    @abstractmethod
    def chunk(self, document: Document, **kwargs) -> list[Chunk]:
        """
        Split a Document into a list of Chunks.
        """
        pass
