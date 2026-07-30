from abc import ABC, abstractmethod
from pathlib import Path

from langparse.core.rendering import document_from_result
from langparse.types import Document, ParsedDocumentResult


class BaseParser(ABC):
    """
    Abstract base class for all document parsers.

    Parsers implement `parse_result`, which returns the structured
    `ParsedDocumentResult` that metrics, quality checks and batch reporting all
    read. `parse` is the flat Markdown view rendered from that same result, so
    the two can never disagree.
    """

    @abstractmethod
    def parse_result(self, file_path: str | Path, **kwargs) -> ParsedDocumentResult:
        """
        Parse a file into its structured page/element/table representation.
        """

    def parse(self, file_path: str | Path, **kwargs) -> Document:
        """
        Parse a file and return the rendered Markdown Document.
        """
        return document_from_result(self.parse_result(file_path, **kwargs))

    @staticmethod
    def _resolve_existing_path(file_path: str | Path) -> Path:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        return path
