from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

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
    elements: list[ParsedElement] = field(default_factory=list)
    tables: list[StructuredData] = field(default_factory=list)
    images: list[StructuredData] = field(default_factory=list)
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
