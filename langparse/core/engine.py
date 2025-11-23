from abc import ABC, abstractmethod
from typing import Any, List, Dict, Iterator
from pathlib import Path
from dataclasses import dataclass

@dataclass
class PageResult:
    """
    Standardized result for a single page from any engine.
    """
    page_number: int
    markdown_content: str
    tables: List[Dict[str, Any]] = None  # Optional structured table data
    images: List[Any] = None             # Optional extracted images

class BaseEngine(ABC):
    """
    Abstract base class for all parsing engines.
    """
    
    @abstractmethod
    def process(self, file_path: Path, **kwargs) -> Iterator[PageResult]:
        """
        Process a file and yield results page by page.
        This allows for streaming processing of large documents.
        """
        pass
