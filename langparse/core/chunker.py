from abc import ABC, abstractmethod
from typing import List
from langparse.types import Document, Chunk

class BaseChunker(ABC):
    """
    Abstract base class for all text chunkers.
    """
    
    @abstractmethod
    def chunk(self, document: Document, **kwargs) -> List[Chunk]:
        """
        Split a Document into a list of Chunks.
        """
        pass
