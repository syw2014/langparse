from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, List

from langparse.types import ParsedElement, StructuredData


@dataclass
class PageResult:
    """
    Engine-facing iterative page result yielded during parsing.
    Mirrors the normalized parsed page shape so engines can stream page data
    before document assembly without carrying a second incompatible contract.
    """
    page_number: int
    markdown_content: str
    plain_text: str = ""
    elements: List[ParsedElement] = field(default_factory=list)
    tables: List[StructuredData] = field(default_factory=list)
    images: List[StructuredData] = field(default_factory=list)
    metadata: StructuredData = field(default_factory=dict)

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
