from importlib.metadata import version as _distribution_version

__version__ = _distribution_version("langparse")

from langparse.autoparser import AutoParser
from langparse.chunkers import (
    FixedTokenChunker,
    SemanticChunker,
    SlidingWindowChunker,
    available_chunkers,
    create_chunker,
    register_chunker,
)
from langparse.core.chunker import BaseChunker
from langparse.core.parser import BaseParser
from langparse.metrics import BatchItemResult, BatchRunResult, ParseMetrics
from langparse.parsers.docx_parser import DocxParser
from langparse.parsers.excel_parser import ExcelParser
from langparse.parsers.markdown_parser import MarkdownParser
from langparse.parsers.pdf_parser import PDFParser
from langparse.progress import ProgressCallback, ProgressEvent
from langparse.types import (
    Chunk,
    Document,
    ParsedDocumentResult,
    ParsedElement,
    ParsedPageResult,
)

__all__ = [
    "__version__",
    "Document",
    "Chunk",
    "ParsedDocumentResult",
    "ParsedPageResult",
    "ParsedElement",
    "BaseParser",
    "BaseChunker",
    "AutoParser",
    "PDFParser",
    "MarkdownParser",
    "DocxParser",
    "ExcelParser",
    "SemanticChunker",
    "FixedTokenChunker",
    "SlidingWindowChunker",
    "available_chunkers",
    "create_chunker",
    "register_chunker",
    "ParseMetrics",
    "ProgressCallback",
    "ProgressEvent",
    "BatchItemResult",
    "BatchRunResult",
]
