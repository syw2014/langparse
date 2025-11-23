from abc import ABC, abstractmethod
from pathlib import Path
from typing import Union
from langparse.types import Document

class BaseParser(ABC):
    """
    Abstract base class for all document parsers.
    """
    
    @abstractmethod
    def parse(self, file_path: Union[str, Path], **kwargs) -> Document:
        """
        Parse a file and return a Document object.
        """
        pass
