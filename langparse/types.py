from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

StructuredData = Dict[str, Any]
BoundingBox = Optional[List[float]]


@dataclass
class Chunk:
    """
    Represents a chunk of text derived from a document.
    """
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Document:
    """
    Represents a parsed document.
    """
    content: str  # The full text content (usually Markdown)
    metadata: Dict[str, Any] = field(default_factory=dict)
    chunks: List[Chunk] = field(default_factory=list)


@dataclass
class ParsedElement:
    kind: str
    text: str = ""
    bbox: BoundingBox = None
    metadata: StructuredData = field(default_factory=dict)


@dataclass
class ParsedPageResult:
    """
    Normalized parsed page result stored in the final document model.
    """
    page_number: int
    markdown_content: str
    plain_text: str = ""
    elements: List[ParsedElement] = field(default_factory=list)
    tables: List[StructuredData] = field(default_factory=list)
    images: List[StructuredData] = field(default_factory=list)
    metadata: StructuredData = field(default_factory=dict)


@dataclass
class ParsedDocumentResult:
    source: str
    filename: str
    engine: str
    pages: List[ParsedPageResult] = field(default_factory=list)
    markdown_content: str = ""
    metadata: StructuredData = field(default_factory=dict)
